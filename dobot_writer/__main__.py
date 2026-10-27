import sys

from .cli import main

if __name__ == "__main__":
    # Sem argumentos (ex.: duplo clique) abre a janela.
    main(sys.argv[1:] or ["gui"])
