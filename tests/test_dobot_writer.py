import struct

import pytest

from dobot_writer import jobs, layout, protocol
from dobot_writer.font import GLYPHS, glyph


class FakeSerial:
    """Simula o Dobot: responde a cada pacote e executa a fila na hora."""

    def __init__(self):
        self.out = bytearray()
        self.commands = []   # (id, write, queued, params)
        self.index = 0
        self.alarms = bytes(16)

    def reset_input_buffer(self):
        self.out.clear()

    def read(self, n):
        data, self.out[:] = bytes(self.out[:n]), self.out[n:]
        return data

    def close(self):
        pass

    def write(self, packet):
        assert packet[:2] == b"\xAA\xAA"
        length = packet[2]
        payload = packet[3:3 + length]
        assert (sum(payload) + packet[3 + length]) & 0xFF == 0
        cmd_id, ctrl, params = payload[0], payload[1], bytes(payload[2:])
        self.commands.append((cmd_id, bool(ctrl & 1), bool(ctrl & 2), params))
        if ctrl & 2:
            self.index += 1
            reply = struct.pack("<Q", self.index)
        elif cmd_id == protocol.ID_GET_POSE:
            reply = struct.pack("<8f", 200, 0, 10, 0, 0, 0, 0, 0)
        elif cmd_id == protocol.ID_GET_ALARMS:
            reply = self.alarms
        elif cmd_id == protocol.ID_QUEUE_CURRENT_INDEX:
            reply = struct.pack("<Q", self.index)
        elif cmd_id == protocol.ID_DEVICE_NAME:
            reply = b"Magician"
        else:
            reply = b""
        self.out += protocol.build_packet(cmd_id, reply, ctrl & 1, ctrl & 2)


def test_packet_checksum():
    # Exemplo do manual: GetPose = AA AA 02 0A 00 F6
    assert protocol.build_packet(10) == bytes([0xAA, 0xAA, 0x02, 0x0A, 0x00, 0xF6])


def test_every_glyph_fits_grid():
    for char, (width, strokes) in GLYPHS.items():
        for s in strokes:
            for x, y in s:
                assert -0.01 <= x <= width + 0.01, char
                assert -2 <= y <= 6, char


def test_accents_and_lowercase():
    assert glyph("a") == glyph("A")
    width, strokes = glyph("ã")
    assert len(strokes) == len(GLYPHS["A"][1]) + 1
    assert len(glyph("ç")[1]) == len(GLYPHS["C"][1]) + 1


def test_layout_size_and_robot_mapping():
    strokes = layout.text_to_strokes("H", 12)
    x0, y0, x1, y1 = layout.bounds(strokes)
    assert y1 - y0 == pytest.approx(12)
    assert (x0 + x1) == pytest.approx(0)
    placed = layout.to_robot(strokes, 230, 0)
    xs = [x for s in placed for x, _ in s]
    ys = [y for s in placed for _, y in s]
    # o "para cima" do texto é +X do robô; largura (8 mm) fica em Y
    assert max(xs) - min(xs) == pytest.approx(12)
    assert max(ys) - min(ys) == pytest.approx(8)
    assert not layout.out_of_reach(placed)
    assert layout.out_of_reach(layout.to_robot(strokes, 400, 0))


def test_write_with_laser_switches_laser_per_stroke():
    fake = FakeSerial()
    dobot = protocol.Dobot(transport=fake)
    placed = layout.to_robot(layout.text_to_strokes("HI", 10), 230, 0)
    jobs.write_on_robot(dobot, placed, z=-40, tool="laser", log=lambda m: None)

    ids = [c[0] for c in fake.commands]
    # a fila é reiniciada antes de começar
    assert ids.index(protocol.ID_QUEUE_START) < ids.index(protocol.ID_PTP_CMD)
    lasers = [c[3][1] for c in fake.commands if c[0] == protocol.ID_END_EFFECTOR_LASER]
    assert lasers[0] == 0 and lasers[-1] == 0
    assert lasers.count(1) == len(placed)
    moves = [struct.unpack("<B4f", c[3]) for c in fake.commands
             if c[0] == protocol.ID_PTP_CMD]
    assert all(m[3] == pytest.approx(-40) for m in moves[1:-1])


def test_write_with_pen_lifts_between_strokes():
    fake = FakeSerial()
    dobot = protocol.Dobot(transport=fake)
    placed = layout.to_robot(layout.text_to_strokes("X", 10), 230, 0)
    jobs.write_on_robot(dobot, placed, z=-50, tool="caneta", log=lambda m: None)
    zs = [struct.unpack("<B4f", c[3])[3] for c in fake.commands
          if c[0] == protocol.ID_PTP_CMD]
    assert -40 in [round(z) for z in zs] and -50 in [round(z) for z in zs]
    assert not any(c[0] == protocol.ID_END_EFFECTOR_LASER for c in fake.commands)


def test_diagnose_clears_alarms():
    fake = FakeSerial()
    fake.alarms = bytes([0, 1] + [0] * 14)
    dobot = protocol.Dobot(transport=fake)
    lines = []
    jobs.diagnose(dobot, log=lines.append)
    assert any("ALARMES" in l for l in lines)
    assert any(c[0] == protocol.ID_CLEAR_ALARMS for c in fake.commands)


def test_stl_is_closed():
    strokes = layout.text_to_strokes("A", 10)
    tris = jobs.strokes_to_triangles(strokes)
    text = jobs.to_stl(tris)
    assert text.startswith("solid") and text.count("facet normal") == len(tris)
    # cada prisma é fechado: cada aresta aparece duas vezes (sentidos opostos)
    edges = {}
    for a, b, c in jobs._prism([(0, 0), (1, 0), (1, 1), (0, 1)], 0, 1):
        for e in ((a, b), (b, c), (c, a)):
            edges[e] = edges.get(e, 0) + 1
    assert all((e[1], e[0]) in edges for e in edges)


def test_gcode_extrudes_increasing():
    g = jobs.strokes_to_gcode(layout.text_to_strokes("L", 10), layers=2)
    assert "M109 S200" in g
    es = [float(w[1:]) for line in g.splitlines() if line.startswith("G1 X")
          for w in line.split() if w.startswith("E")]
    assert es == sorted(es) and es[-1] > 0
