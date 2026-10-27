"""Comunicação direta com o Dobot Magician pela porta série (USB).

Implementa o "Dobot Magician Communication Protocol" (pacotes 0xAA 0xAA),
o mesmo que o DobotStudio usa por baixo. Não precisa da DLL da Dobot.

Formato do pacote:
    0xAA 0xAA | Len | ID | Ctrl | Params... | Checksum
    Len = 2 + len(Params); Ctrl bit0 = escrita, bit1 = fila (queued)
    Checksum = complemento para dois da soma de ID + Ctrl + Params
"""

import struct
import threading
import time

BAUDRATE = 115200

ID_DEVICE_NAME = 1
ID_GET_POSE = 10
ID_GET_ALARMS = 20
ID_CLEAR_ALARMS = 21
ID_SET_HOME = 31
ID_END_EFFECTOR_PARAMS = 60
ID_END_EFFECTOR_LASER = 61
ID_PTP_COORD_PARAMS = 81
ID_PTP_COMMON_PARAMS = 83
ID_PTP_CMD = 84
ID_WAIT = 110
ID_QUEUE_START = 240
ID_QUEUE_STOP = 241
ID_QUEUE_FORCE_STOP = 242
ID_QUEUE_CLEAR = 245
ID_QUEUE_CURRENT_INDEX = 246

PTP_JUMP_XYZ = 0
PTP_MOVJ_XYZ = 1
PTP_MOVL_XYZ = 2


class DobotError(Exception):
    pass


class Aborted(DobotError):
    pass


def build_packet(cmd_id, params=b"", write=False, queued=False):
    ctrl = (1 if write else 0) | (2 if queued else 0)
    payload = bytes([cmd_id, ctrl]) + bytes(params)
    checksum = (-sum(payload)) & 0xFF
    return b"\xAA\xAA" + bytes([len(payload)]) + payload + bytes([checksum])


def list_serial_ports():
    try:
        from serial.tools import list_ports
    except ImportError:
        return []
    return [p.device for p in list_ports.comports()]


class Dobot:
    """Ligação a um Dobot Magician.

    `transport` permite injetar um objeto tipo serial (para testes).
    `max_ahead` limita quantos comandos ficam pendentes na fila do robô, para
    nunca a encher (a fila interna tem poucas dezenas de posições).
    """

    def __init__(self, port=None, transport=None, timeout=1.0, max_ahead=12):
        if transport is None:
            import serial  # pyserial
            transport = serial.Serial(port, BAUDRATE, timeout=timeout)
            time.sleep(0.5)
        self.ser = transport
        self.max_ahead = max_ahead
        self.last_index = None
        self.abort_event = threading.Event()
        self._lock = threading.Lock()

    def close(self):
        self.ser.close()

    # --- nível baixo -----------------------------------------------------

    def _read_exact(self, n):
        data = self.ser.read(n)
        if len(data) != n:
            raise DobotError(
                "O robô não respondeu. Confirme o cabo USB, a porta escolhida, "
                "que o robô está ligado e que o DobotStudio está FECHADO."
            )
        return data

    def _read_packet(self):
        prev = None
        for _ in range(512):
            b = self._read_exact(1)[0]
            if prev == 0xAA and b == 0xAA:
                break
            prev = b
        else:
            raise DobotError("Resposta inválida do robô (sem cabeçalho)")
        length = self._read_exact(1)[0]
        payload = self._read_exact(length)
        checksum = self._read_exact(1)[0]
        if (sum(payload) + checksum) & 0xFF:
            raise DobotError("Resposta do robô com checksum errado")
        return payload[0], payload[2:]

    def send(self, cmd_id, params=b"", write=False, queued=False):
        with self._lock:
            self.ser.reset_input_buffer()
            self.ser.write(build_packet(cmd_id, params, write, queued))
            for _ in range(4):
                rid, data = self._read_packet()
                if rid == cmd_id:
                    return data
        raise DobotError(f"Resposta inesperada ao comando {cmd_id}")

    def _queued(self, cmd_id, params=b""):
        self._throttle()
        data = self.send(cmd_id, params, write=True, queued=True)
        if len(data) < 8:
            raise DobotError("O robô recusou o comando (fila cheia?)")
        self.last_index = struct.unpack("<Q", data[:8])[0]
        return self.last_index

    def _throttle(self):
        if self.last_index is None:
            return
        while self.last_index - self.current_index() >= self.max_ahead:
            self._check_abort()
            time.sleep(0.05)

    def _check_abort(self):
        if self.abort_event.is_set():
            raise Aborted("Trabalho interrompido")

    # --- informação ------------------------------------------------------

    def device_name(self):
        return self.send(ID_DEVICE_NAME).decode("ascii", "replace").strip("\x00")

    def get_pose(self):
        """(x, y, z, r) em mm/graus."""
        data = self.send(ID_GET_POSE)
        return struct.unpack("<4f", data[:16])

    def get_alarms(self):
        """Lista dos códigos de alarme ativos (vazia = sem alarmes)."""
        data = self.send(ID_GET_ALARMS)
        return [i * 8 + bit for i, byte in enumerate(data)
                for bit in range(8) if byte >> bit & 1]

    def clear_alarms(self):
        self.send(ID_CLEAR_ALARMS, write=True)

    def current_index(self):
        data = self.send(ID_QUEUE_CURRENT_INDEX)
        return struct.unpack("<Q", data[:8])[0]

    # --- fila de comandos ------------------------------------------------

    def queue_start(self):
        self.send(ID_QUEUE_START, write=True)

    def queue_stop(self):
        self.send(ID_QUEUE_STOP, write=True)

    def queue_force_stop(self):
        self.send(ID_QUEUE_FORCE_STOP, write=True)

    def queue_clear(self):
        self.send(ID_QUEUE_CLEAR, write=True)
        self.last_index = None

    def reset_queue(self):
        """Para, limpa e volta a arrancar a fila. Se a fila estiver parada
        (por exemplo depois de um "Stop" no DobotStudio), nenhum comando
        programado é executado, embora o movimento manual funcione."""
        self.queue_force_stop()
        self.queue_clear()
        self.queue_start()

    def wait_until_done(self, index=None, timeout=None):
        index = self.last_index if index is None else index
        if index is None:
            return
        start = time.time()
        while self.current_index() < index:
            self._check_abort()
            if timeout and time.time() - start > timeout:
                raise DobotError("O robô não terminou os movimentos a tempo")
            time.sleep(0.1)

    # --- parâmetros e movimentos -----------------------------------------

    def set_end_effector_offset(self, x, y=0.0, z=0.0):
        self.send(ID_END_EFFECTOR_PARAMS, struct.pack("<3f", x, y, z), write=True)

    def set_speed(self, velocity_mm_s, acceleration_mm_s2):
        self.send(ID_PTP_COORD_PARAMS,
                  struct.pack("<4f", velocity_mm_s, velocity_mm_s,
                              acceleration_mm_s2, acceleration_mm_s2),
                  write=True)
        self.send(ID_PTP_COMMON_PARAMS, struct.pack("<2f", 100, 100), write=True)

    def queue_speed_ratio(self, percent):
        """Muda a velocidade (percentagem da definida em set_speed) na fila."""
        return self._queued(ID_PTP_COMMON_PARAMS, struct.pack("<2f", percent, 100))

    def home(self):
        return self._queued(ID_SET_HOME, struct.pack("<I", 0))

    def move(self, x, y, z, r=0.0, mode=PTP_MOVL_XYZ):
        self._check_abort()
        return self._queued(ID_PTP_CMD, struct.pack("<B4f", mode, x, y, z, r))

    def wait_ms(self, ms):
        return self._queued(ID_WAIT, struct.pack("<I", int(ms)))

    def laser(self, on, queued=True):
        params = bytes([1, 1 if on else 0])
        if queued:
            return self._queued(ID_END_EFFECTOR_LASER, params)
        self.send(ID_END_EFFECTOR_LASER, params, write=True)
        return None
