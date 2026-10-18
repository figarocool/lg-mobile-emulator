"""Model of the camera QDSP image (image 0x15: VFE, camera interface and JPEG helpers) at the ARM interface.

The DSP code is not executed. The ARM driver (camqdsp_drv.c) talks to the image through words in DSP memory:
  * the command register (0x58000002): the driver marks it 0xffff while the image is not up, the booted image frees it (0)
  * command words (id written last, payload before it) followed by a doorbell write (0x58c00004 = 1)
  * event words that the driver's ISR (IRQ 10) polls and clears; a nonzero value raises one camera event
"""
import os
from unicorn import UC_HOOK_MEM_READ, UC_HOOK_MEM_WRITE
from camera_source import ENCODERS, make_source


class CameraDsp:
    COMMAND = 0x58000002
    NOT_BOOTED = 0xffff
    DOORBELL = 0x58c00004
    IRQ = 10
    # command words: address -> (payload address, payload size)
    SLOTS = {0x58401918: (0x5840191c, 0x5c), 0x58204008: (0x5820400a, 0x10), 0x58400cf8: (0x58400cfc, 0x84),
             0x5840324c: (0x58403250, 0x18)}  # 0x200/0x201 (YCbCr downsize image) use the last slot
    # event words polled by the ARM ISR (camqdsp_drv.c): name -> address
    EVENTS = {'error': 0x58401a18, 'illegal': 0x58401a30, 'images_ready': 0x584019f4, 'idle': 0x58401a20,
              'ev_a': 0x58401a24, 'handoff': 0x58401a2c, 'config_done': 0x58401a1c, 'jpeg_buf': 0x584026c0}

    def __init__(self, uc, qdsp):
        self.uc = uc
        self.qdsp = qdsp
        self.log = []
        self.pending = []
        self.grp = None
        self.ticks = 0
        self.handlers = {}
        self.handlers[0x800] = self.config
        self.handlers[0x801] = self.start
        self.handlers[0x802] = self.stop
        self.source = make_source(os.environ.get('U310_CAMERA'))
        self.buffers = []
        self.last = None
        self.handlers[0x200] = self.downsize_config
        self.handlers[0x201] = self.downsize_start
        self.downsize = None
        self.downsize_done = False
        self.format = int(os.environ.get('U310_CAMFMT', '4'))
        self.encoding = os.environ.get('U310_CAMENC', 'uyvy')
        self.size = (288, 216)
        self.streaming = False
        self.frames = 0
        self.next_buffer = 0
        import atexit
        if os.environ.get('U310_CAMLOG'):
            atexit.register(lambda: open(os.environ['U310_CAMLOG'], 'w').write('\n'.join(map(str, self.log))))
        uc.hook_add(UC_HOOK_MEM_READ, self.command_read, begin=self.COMMAND, end=self.COMMAND + 1)
        uc.hook_add(UC_HOOK_MEM_WRITE, self.doorbell, begin=self.DOORBELL, end=self.DOORBELL + 3)
        # 0x19b5331/0x19b5349: ARM-side "YCbCr downsize busy" flags (camqdsp_drv.c, 0x10b5968/0x10bb2a0..0x10bb390).
        # Something re-arms them between our handler running and the ARM's check (not fully reversed), so the
        # read itself is forced to "done" once a downsize job has actually completed, rather than racing a write.
        uc.hook_add(UC_HOOK_MEM_READ, self.downsize_flag_read, begin=0x19b5331, end=0x19b5331)
        uc.hook_add(UC_HOOK_MEM_READ, self.downsize_flag_read, begin=0x19b5349, end=0x19b5349)

    def downsize_flag_read(self, uc, access, address, size, value, _):
        if self.downsize_done:
            uc.mem_write(address, b'\x00')

    def command_read(self, uc, access, address, size, value, _):
        if int.from_bytes(uc.mem_read(self.COMMAND, 2), 'little') == self.NOT_BOOTED:
            uc.mem_write(self.COMMAND, b'\x00\x00')

    def word(self, address, size=4):
        return int.from_bytes(self.uc.mem_read(address, size), 'little')

    def doorbell(self, uc, access, address, size, value, _):
        # Some ARM-side waits (e.g. the YCbCr downsize job) check completion after a short,
        # size-proportional delay with no retry, so the command is resolved immediately rather
        # than deferred a few ticks like the audio QDSP model does.
        if value & 1:
            self.collect()

    def collect(self):
        for slot, (payload, length) in self.SLOTS.items():
            command = self.word(slot)
            if command & 0xffff and command != self.NOT_BOOTED:
                data = bytes(self.uc.mem_read(payload, length))
                self.log.append(('CMD', self.ticks, hex(command & 0xffff), hex(slot)))
                self.uc.mem_write(slot, b'\0\0\0\0')
                handler = self.handlers.get(command & 0xffff)
                if handler:
                    handler(command & 0xffff, data)

    FRAME_TICKS = 600          # advance() calls between preview frames (about 15 per second)
    STARTED = 0x17e55cc        # byte set by the driver when the VFE is started and re-armed after every frame event

    def config(self, command, data):
        words = [int.from_bytes(data[i:i + 4], 'little') for i in range(0, len(data), 4)]
        self.buffers = [w for w in words[4:6] if w]
        if self.buffers:
            header = self.find_header(self.buffers[0])
            if header is not None:
                width, height = (int.from_bytes(self.uc.mem_read(header + off, 2), 'little') for off in (0x1a, 0x1c))
                if width and height:
                    self.size = (width, height)
        self.post('config_done')

    def find_header(self, pixels):
        """The QCAM frame header (written by the LG camera layer) in front of a pixel pointer: data offset 0x40 plus the word at +0x30."""
        for back in range(0x40, 0x80, 4):
            address = pixels - back
            try:
                if bytes(self.uc.mem_read(address, 8)) == b'QCAMRAW ' and self.word(address + 8) + self.word(address + 0x30) == back:
                    return address
            except Exception:
                pass
        return None

    def downsize_config(self, command, data):
        self.downsize_done = False
        words = [int.from_bytes(data[i:i + 4], 'little') for i in range(0, 0x18, 4)]
        self.downsize = {'src_height': words[0] & 0xffff, 'src_width': words[0] >> 16, 'src': words[2],
                         'dst_height': words[3] & 0xffff, 'dst_width': words[3] >> 16, 'dst': words[5]}
        self.log.append(('downsize', self.downsize))

    def downsize_start(self, command, data):
        job = self.downsize
        if job and self.last is not None:
            from camera_source import fit
            small = fit(self.last, job['dst_width'], job['dst_height'])
            self.uc.mem_write(job['dst'], ENCODERS[self.encoding](small))
        self.post('idle')
        self.downsize_done = True

    def stop(self, command, data):
        self.streaming = False
        self.post('idle')

    def start(self, command, data):
        self.streaming = True
        self.pending.append((self.ticks + self.FRAME_TICKS, self.frame))

    def frame(self):
        if not self.streaming or not self.buffers:
            return
        if self.word(self.EVENTS['images_ready']) or not self.uc.mem_read(self.STARTED, 1)[0]:
            self.log.append(('wait', self.word(self.EVENTS['images_ready']), self.uc.mem_read(self.STARTED, 1)[0])) if len(self.log) < 60 else None
            self.pending.append((self.ticks + 8, self.frame))
            return
        width, height = self.size
        rgb = self.source.frame(width, height)
        if rgb is not None:
            data = ENCODERS[self.encoding](rgb)
            buffer = self.buffers[self.next_buffer % len(self.buffers)]
            self.next_buffer += 1
            self.uc.mem_write(buffer, data)
            header = self.find_header(buffer)
            if header is not None:
                self.uc.mem_write(header + 0x10, bytes([self.format, 1]))   # frame header: pixel format, valid
            self.last = rgb
            self.uc.mem_write(0x584019f8, (4).to_bytes(4, 'little') + buffer.to_bytes(4, 'little') + bytes(4))
            self.frames += 1
            self.log.append(('frame', self.frames, hex(buffer), self.size))
            self.post('images_ready')
        self.pending.append((self.ticks + self.FRAME_TICKS, self.frame))

    def post(self, name, value=1):
        self.uc.mem_write(self.EVENTS[name], value.to_bytes(4, 'little'))
        self.qdsp.interrupts.raise_source(self.IRQ)

    def attach_display(self, panel):
        from grp_dma import GrpDma
        self.grp = GrpDma(self.uc, panel)

    def advance(self):
        self.ticks += 1
        if self.grp:
            self.grp.service()
        due = [p for p in self.pending if p[0] <= self.ticks]
        self.pending = [p for p in self.pending if p[0] > self.ticks]
        for _, action in due:
            action()

    def report(self):
        return {'log': self.log[:80]}
