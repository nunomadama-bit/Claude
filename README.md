# Dobot Writer

Aplicação para escrever palavras com o braço robótico **Dobot Magician**:

- **Laser**: grava o texto diretamente (o laser liga em cada traço e desliga entre traços).
- **Caneta**: o mesmo percurso com caneta, para testar sem risco.
- **Impressão 3D**: exporta as letras em relevo (**STL**) ou um **G-code** para o firmware 3D.

Fala diretamente com o robô pela porta USB, com o protocolo oficial do Dobot.
Não precisa do DobotStudio nem da DLL da Dobot.

> ⚠️ Esta aplicação corre num **computador (Windows, macOS ou Linux) ligado ao robô por cabo USB**.
> O iPad não serve para isto: a app de iPad é muito limitada e não controla o laser nem a impressão 3D.

---

## 1. Antes de programar: porque é que o robô não faz nada?

Se o braço se mexe nos comandos manuais (jog) e no *Home*, a parte mecânica e os motores estão bons.
Quando os **programas** (laser, escrita, 3D) não fazem nada, a causa costuma ser uma destas:

| Sintoma | Causa provável | Solução |
|---|---|---|
| Jog funciona, mas nenhum programa corre | **Fila de comandos parada** (fica assim depois de um *Stop*/erro) ou **alarme ativo** (LED vermelho) | Faça *Home*; LED tem de ficar **verde**. O `diagnostico` desta app limpa alarmes e reinicia a fila. |
| Laser não acende | Cabos trocados ou **ferramenta errada selecionada** | Cabo de **alimentação** do laser na porta **SW4**, cabo de **sinal** na porta **GP5** (no antebraço). No DobotStudio escolha *End Tool → Laser*. |
| Laser acende só um instante / muito fraco | Laser fora de foco | Ajuste a altura Z até o ponto ficar mínimo (e/ou rode a lente do módulo). |
| 3D não faz nada | **O firmware normal não imprime em 3D** | No DobotStudio: *Firmware → 3D Printer* (Marlin). Depois imprime-se pelo **Repetier‑Host**, não pelo DobotStudio. Para voltar ao laser, volte a pôr o firmware *Dobot* normal. |
| 3D mexe mas não sai plástico | Bico frio (Marlin não extrude abaixo de ~170 °C) ou cabos | Aquecedor na **SW1**, termístor na **ANALOG**, motor do extrusor na **Stepper1**. Espere pelos 200 °C. |
| Nada responde por USB | DobotStudio aberto ao mesmo tempo, porta errada, driver | Feche o DobotStudio. Instale o driver USB (CH340/CP210x) que vem com o DobotStudio. |
| Movimento para a meio | Ponto fora do alcance | Use posições entre ~150 e ~315 mm da base. |

Também convém **atualizar o firmware** no DobotStudio (*Firmware Update*) e fazer *Home* sempre que ligar o robô.

---

## 2. Instalação

1. Instale o **Python 3.9+** (python.org). No Windows marque *"Add Python to PATH"*.
2. Descarregue esta pasta e, numa linha de comandos dentro dela:

   ```bash
   pip install -r requirements.txt
   ```

3. Ligue o robô por USB, ligue-o, faça *Home* e **feche o DobotStudio**.

## 3. Usar a janela

```bash
python -m dobot_writer
```

1. Escolha a porta (ex.: `COM3` no Windows, `/dev/tty.usbserial…` no Mac) e carregue em **Ligar**.
2. Carregue em **Diagnóstico**. Se aparecer "OK: o robô executa comandos programados", a ligação e a fila estão boas.
3. Com o laser montado, baixe o braço com o DobotStudio/botões até o laser estar focado na superfície,
   (feche o DobotStudio) e carregue em **Ler Z do robô**.
4. Escreva o texto, ajuste a altura das letras e o centro (X≈230, Y=0 fica à frente do robô).
5. Experimente primeiro com **Caneta**, depois **Laser**. **Use sempre os óculos de proteção do laser.**
6. **■ PARAR** para e desliga o laser imediatamente.

## 4. Linha de comandos

```bash
python -m dobot_writer portas                              # lista as portas USB
python -m dobot_writer diagnostico --porta COM3 --laser    # testa tudo (laser 1 s)
python -m dobot_writer posicao --porta COM3                # lê X Y Z (para saber o Z)
python -m dobot_writer previsualizar "OLÁ" -o ola.svg      # ver o resultado antes
python -m dobot_writer escrever "OLÁ MUNDO" --z -45 --altura 15 --porta COM3
python -m dobot_writer escrever "TESTE" --ferramenta caneta --z -55
python -m dobot_writer stl "NUNO" --altura 20 -o nuno.stl  # letras em relevo para 3D
python -m dobot_writer gcode "NUNO" --x 0 --y 0 -o nuno.gcode
```

Use `\n` no texto para várias linhas. As letras minúsculas são escritas em maiúsculas; os acentos
portugueses (á à â ã ç ê é í ó ô õ ú) são suportados.

Velocidade a gravar com laser: 5–20 mm/s (mais lento = mais escuro). A "pausa laser" é o tempo que o
laser fica parado no início de cada traço para começar a queimar.

## 5. Impressão 3D

O Dobot só imprime em 3D com o **firmware 3D** e o **Repetier‑Host** (configurações da Dobot).

- **Recomendado: STL.** Exporte o STL (letras em relevo sobre uma placa de 1 mm), abra no Repetier‑Host,
  fatie (*Slice*) com o perfil da Dobot e imprima.
- **G-code direto:** exporta o percurso das letras, camada a camada. As coordenadas `--x/--y` são as do
  referencial da impressora no Repetier‑Host; confirme‑as (mova o bico manualmente) antes de imprimir.

## 6. Estrutura

```
dobot_writer/
  protocol.py  comunicação USB com o Dobot (pacotes AA AA, fila, laser, movimentos)
  font.py      fonte de traço simples (letras, números, acentos)
  layout.py    texto -> traços em mm -> posições do robô; pré-visualização SVG
  jobs.py      escrever (laser/caneta), diagnóstico, STL e G-code
  gui.py       janela (tkinter)
  cli.py       linha de comandos
tests/         testes com um robô simulado (pytest)
```

O offset da ferramenta (distância da ponta ao último motor) está em `jobs.TOOL_OFFSETS`
(laser 70 mm, caneta 61 mm). Se as letras saírem deslocadas, ajuste‑o ao valor do seu kit
ou use `--sem-offset` para manter o que está configurado no DobotStudio.
