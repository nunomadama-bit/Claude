"""Linha de comandos: python -m dobot_writer <comando> ..."""

import argparse
import sys

from . import jobs, layout
from .protocol import Dobot, DobotError, list_serial_ports


def _add_text_args(p):
    p.add_argument("texto", help="texto a escrever (use \\n para mudar de linha)")
    p.add_argument("--altura", type=float, default=15.0,
                   help="altura das letras maiúsculas em mm (defeito 15)")


def _text(args):
    return args.texto.replace("\\n", "\n")


def _connect(args):
    port = args.porta or (list_serial_ports() or [None])[0]
    if not port:
        sys.exit("Nenhuma porta série encontrada. Ligue o robô por USB.")
    print(f"A ligar a {port}...")
    return Dobot(port)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="dobot_writer",
                                 description="Escrever palavras com o Dobot Magician")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("portas", help="lista as portas série disponíveis")
    sub.add_parser("gui", help="abre a janela da aplicação")

    p = sub.add_parser("diagnostico", help="testa a ligação, alarmes, fila e laser")
    p.add_argument("--porta")
    p.add_argument("--laser", action="store_true", help="liga o laser 1 s")

    p = sub.add_parser("posicao", help="mostra a posição atual (use para ler o Z)")
    p.add_argument("--porta")

    p = sub.add_parser("previsualizar", help="gera um SVG com o texto")
    _add_text_args(p)
    p.add_argument("-o", "--saida", default="texto.svg")

    p = sub.add_parser("escrever", help="escreve com laser ou caneta")
    _add_text_args(p)
    p.add_argument("--porta")
    p.add_argument("--ferramenta", choices=["laser", "caneta"], default="laser")
    p.add_argument("--z", type=float, required=True,
                   help="altura Z da superfície/foco (leia com 'posicao')")
    p.add_argument("--x", type=float, default=230.0, help="centro do texto X")
    p.add_argument("--y", type=float, default=0.0, help="centro do texto Y")
    p.add_argument("--rotacao", type=float, default=0.0)
    p.add_argument("--velocidade", type=float, default=15.0,
                   help="velocidade a escrever/gravar mm/s (defeito 15)")
    p.add_argument("--pausa-laser", type=int, default=150,
                   help="ms com o laser parado no início de cada traço")
    p.add_argument("--sem-offset", action="store_true",
                   help="não alterar o offset da ferramenta no robô")

    p = sub.add_parser("stl", help="letras em relevo para impressão 3D (STL)")
    _add_text_args(p)
    p.add_argument("-o", "--saida", default="texto.stl")
    p.add_argument("--largura-traco", type=float, default=1.6)
    p.add_argument("--relevo", type=float, default=3.0, help="altura das letras mm")
    p.add_argument("--base", type=float, default=1.0, help="placa por baixo mm (0 = sem)")

    p = sub.add_parser("gcode", help="G-code para o firmware 3D do Dobot")
    _add_text_args(p)
    p.add_argument("-o", "--saida", default="texto.gcode")
    p.add_argument("--x", type=float, default=0.0, help="centro X da impressora")
    p.add_argument("--y", type=float, default=0.0, help="centro Y da impressora")
    p.add_argument("--camadas", type=int, default=8)
    p.add_argument("--temperatura", type=int, default=200)

    args = ap.parse_args(argv)

    if args.cmd == "portas":
        print("\n".join(list_serial_ports()) or "Nenhuma porta encontrada.")
    elif args.cmd == "gui":
        from .gui import run
        run()
    elif args.cmd == "previsualizar":
        strokes = layout.text_to_strokes(_text(args), args.altura)
        with open(args.saida, "w", encoding="utf-8") as f:
            f.write(layout.to_svg(strokes))
        print(f"Gravado {args.saida}")
    elif args.cmd == "stl":
        strokes = layout.text_to_strokes(_text(args), args.altura)
        tris = jobs.strokes_to_triangles(strokes, args.largura_traco,
                                         args.relevo, args.base)
        with open(args.saida, "w", encoding="ascii") as f:
            f.write(jobs.to_stl(tris))
        print(f"Gravado {args.saida} ({len(tris)} triângulos)")
    elif args.cmd == "gcode":
        strokes = layout.text_to_strokes(_text(args), args.altura)
        with open(args.saida, "w", encoding="ascii") as f:
            f.write(jobs.strokes_to_gcode(strokes, args.x, args.y,
                                          layers=args.camadas,
                                          temperature=args.temperatura))
        print(f"Gravado {args.saida}")
    else:
        try:
            _run_robot(args)
        except DobotError as exc:
            sys.exit(f"ERRO: {exc}")


def _run_robot(args):
    dobot = _connect(args)
    try:
        if args.cmd == "diagnostico":
            ok = jobs.diagnose(dobot, test_laser=args.laser)
            print("Diagnóstico OK." if ok else "Diagnóstico encontrou problemas.")
        elif args.cmd == "posicao":
            x, y, z, r = dobot.get_pose()
            print(f"X={x:.2f} Y={y:.2f} Z={z:.2f} R={r:.2f}")
        elif args.cmd == "escrever":
            strokes = layout.text_to_strokes(_text(args), args.altura)
            placed = layout.to_robot(strokes, args.x, args.y, args.rotacao)
            bad = layout.out_of_reach(placed)
            if bad:
                sys.exit(f"{len(bad)} pontos fora do alcance do braço. Reduza a "
                         "altura das letras ou mude --x/--y.")
            print(f"{len(placed)} traços, {layout.path_length(placed):.0f} mm a "
                  "desenhar. Ctrl+C para parar.")
            try:
                jobs.write_on_robot(
                    dobot, placed, args.z, tool=args.ferramenta,
                    draw_speed=args.velocidade, dwell_ms=args.pausa_laser,
                    set_tool_offset=not args.sem_offset,
                    progress=lambda n, t: print(f"\r  traço {n}/{t}", end=""))
            except KeyboardInterrupt:
                jobs.stop(dobot)
                print("\nParado.")
    finally:
        dobot.close()


if __name__ == "__main__":
    main()
