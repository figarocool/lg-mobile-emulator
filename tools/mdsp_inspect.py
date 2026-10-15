"""Read-only AMSS MDSP state, inferred from 0x48288c and 0x482b12."""
from unicorn import UcError


def inspect_mdsp(uc):
    try:
        state = bytes(uc.mem_read(0x019a3970, 0x18))
        command = int.from_bytes(uc.mem_read(0x50206310, 2), 'little')
        response = int.from_bytes(uc.mem_read(0x5040b37c, 4), 'little')
        request = int.from_bytes(uc.mem_read(0x5040b380, 4), 'little')
    except UcError:
        return {'available': False}
    expected = int.from_bytes(state[0x10:0x14], 'little')
    return {'available': True, 'management_state': state[0],
            'module_mask_expected': hex(expected), 'module_mask_request': hex(request),
            'module_mask_response': hex(response), 'mailbox_command': command,
            'completion_conditions_met': state[0] == 2 and command == 0 and response == expected,
            'source': 'original ARM routines 0x48288c and 0x482b12',
            'executes_dsp_code': False}
