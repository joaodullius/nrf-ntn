# nrf-ntn

Coleção de scripts para testar e analisar conectividade NTN (Non-Terrestrial Network) via satélite
em modems celulares Nordic nRF91xx (nRF9151, usado tanto para SatelIoT quanto para Skylo), incluindo previsão
de passagens de satélites LEO, configuração via comandos AT e captura de trace LTE alinhada às
passagens.

## Índice

- [Pré-requisitos](#pré-requisitos)
- [Aviso sobre coordenadas padrão](#aviso-sobre-coordenadas-padrão)
- [get_tle.py](#get_tlepy)
- [leo_next_passes.py](#leo_next_passespy)
- [skylo_test.py](#skylo_testpy)
- [sateliot_quick_test.py](#sateliot_quick_testpy)
- [get_trace.py](#get_tracepy)

## Pré-requisitos

Instale as dependências Python com:

```bash
pip install -r requirements.txt
```

O `get_trace.py` também requer o CLI `nrfutil` (com o comando `trace`) instalado e disponível no
`PATH`.

Vários scripts (`get_tle.py`, `leo_next_passes.py`, `get_trace.py`) buscam os TLEs através do módulo
compartilhado `tle_fetcher.py`, que tenta, em ordem: **CelesTrak** (sem autenticação) → **N2YO**
(requer chave de API) → **SatNOGS** (sem autenticação). A chave do N2YO é opcional e só é usada se
o CelesTrak falhar; pode ser definida via variável de ambiente `N2YO_API_KEY` ou em um arquivo local
`config.py` (não versionado) com `N2YO_API_KEY = "sua_chave"`.

---

## Aviso sobre coordenadas padrão

> Por conveniência, vários scripts (`leo_next_passes.py`, `get_trace.py`, `skylo_test.py`,
> `sateliot_quick_test.py`) têm latitude/longitude padrão fixas (*hardcoded*) no código. Antes de
> usar, troque esses valores pela localização real do seu observador — via os argumentos
> `--lat`/`--lon` de cada script, ou editando as constantes `LATITUDE`/`LONGITUDE` /
> `DEFAULT_LAT`/`DEFAULT_LON` no topo de cada arquivo.

---

## `get_tle.py`

Busca e imprime os dados orbitais (TLE) atuais dos 4 satélites SatelIoT cadastrados, usando
`tle_fetcher.py` (com fallback automático CelesTrak → N2YO → SatNOGS).

Não recebe argumentos de linha de comando.

### Exemplo de uso

```bash
python get_tle.py
```

Saída esperada (uma entrada por satélite):

```
SATELIOT_1
1 60550U 24149CL  26169.69643206  .00002324  00000+0  20121-3 0  9995
2 60550  97.6757 245.5690 0008414  76.1756 284.0402 14.98076192100298
```

---

## `leo_next_passes.py`

Calcula e exibe as próximas passagens visíveis dos satélites LEO sobre uma posição de observador,
usando Skyfield. Também busca os TLEs via `tle_fetcher.py` (mesmo fallback CelesTrak → N2YO →
SatNOGS usado por `get_tle.py`). Opcionalmente gera gráficos polares de céu (sky-plots) e mapas de
trajetória no solo (ground tracks).

### Argumentos

| Argumento | Padrão | Descrição |
|---|---|---|
| `--clean` | — | Apaga as pastas `plots/` e `maps/` antes de continuar |
| `-p`, `--plot` | — | Gera imagens `.png` de sky-plot para cada passagem |
| `-m`, `--map` | — | Gera mapas `.html` de trajetória no solo |
| `-e`, `--min-elevation DEG` | `45` | Elevação mínima (graus) para considerar uma passagem |
| `-a`, `--min-azimuth DEG` | `0` | Azimute mínimo da janela de visada (graus) |
| `-A`, `--max-azimuth DEG` | `360` | Azimute máximo da janela de visada (graus) |
| `-s`, `--satellites NOME...` | todos | Satélites a rastrear (`SATELIOT_1`, `SATELIOT_2`, `SATELIOT_3`, `SATELIOT_4`) |
| `--lat DEG` | `-30.065361` | Latitude do observador |
| `--lon DEG` | `-51.235283` | Longitude do observador |
| `-d`, `--days DIAS` | `2` | Janela de busca (dias a partir do início) |
| `--utc-offset HORAS` | auto | Offset UTC manual (sobrepõe a detecção automática pela posição) |
| `--start DATETIME_OU_DIAS` | agora | Início da busca: número negativo de dias atrás (ex: `-2`) ou data UTC `"YYYY-MM-DD HH:MM"` |
| `--tle` | — | Imprime as linhas de TLE usadas em cada passagem |

### Exemplos de uso

```bash
# Próximas passagens (padrão: 2 dias, elevação mínima 45°)
python leo_next_passes.py

# Gerar sky-plots e mapas de trajetória
python leo_next_passes.py --plot --map

# Filtrar por elevação mínima de 60° e janela de azimute (leste, 45°-135°)
python leo_next_passes.py -e 60 -a 45 -A 135

# Rastrear apenas dois satélites específicos, por 5 dias
python leo_next_passes.py -s SATELIOT_1 SATELIOT_3 -d 5

# Usar outra localização (e fuso manual) e buscar a partir de 1 dia atrás
python leo_next_passes.py --lat -23.55 --lon -46.63 --utc-offset -3 --start -1

# Limpar gráficos/mapas antigos e gerar novos, exibindo o TLE de cada satélite
python leo_next_passes.py --clean --plot --tle
```

---

## `skylo_test.py`

Configura um modem nRF9151 para conectividade NTN via Skylo, enviando uma sequência de comandos AT
(informações do modem, modo de sistema NTN, bloqueio de banda, localização, notificações de URC e
ativação do modem), com decodificação em tempo real das URCs (`%CESQ`, `+CEREG`, `+CSCON`). Após o
setup, abre um shell interativo de comandos AT com atalhos numéricos para testes de socket UDP.

### Argumentos

| Argumento | Padrão | Descrição |
|---|---|---|
| `-p`, `--port` | *(obrigatório)* | Porta serial (ex: `COM26` ou `/dev/ttyUSB0`) |
| `-b`, `--baud` | `115200` | Baud rate |
| `--lat` | `-30.065361` | Latitude do observador |
| `--lon` | `-51.235283` | Longitude do observador |
| `--alt` | `10` | Altitude do observador (metros) |
| `-g`, `--gnss` | — | Obtém a posição atual via fixação GNSS (sobrepõe `--lat`/`--lon`) |
| `-s`, `--save NOME` | — | Salva o log em `NOME_AAAAMMDD_HHMMSS.log` |
| `--timestamp` | — | Prefixa cada mensagem com timestamp |

### Atalhos do shell interativo

| Tecla | Ação |
|---|---|
| `1` | Cria e conecta um socket UDP |
| `2` | Envia uma mensagem de teste (contador automático) |
| `3` | Recebe dados do socket |
| `4` | Fecha o socket |
| `exit` / `Ctrl+C` | Sai do shell |

Qualquer outro texto digitado é tratado como comando AT (o prefixo `AT` é adicionado se ausente).

### Exemplos de uso

```bash
# Setup básico com localização padrão (Porto Alegre)
python skylo_test.py --port COM26

# Obter a posição via GNSS antes do setup
python skylo_test.py --port COM26 --gnss

# Informar localização manualmente e salvar log com timestamp
python skylo_test.py --port COM26 --lat -30.065 --lon -51.235 --save skylo_session --timestamp
```

---

## `sateliot_quick_test.py`

Configura um modem nRF9151 para conectividade NTN via SatelIoT, enviando uma sequência de comandos
AT (informações do modem, seleção manual do operador SatelIoT, modo de sistema NTN, bloqueio de
banda, configuração de busca periódica de célula, localização e notificações de URC), com a mesma
decodificação de URCs em tempo real usada em `skylo_test.py`. Após o setup, abre um shell interativo
de comandos AT.

### Argumentos

| Argumento | Padrão | Descrição |
|---|---|---|
| `-p`, `--port` | *(obrigatório)* | Porta serial (ex: `COM3` ou `/dev/ttyUSB0`) |
| `-b`, `--baud` | `115200` | Baud rate |
| `--lat` | `-30.065361` | Latitude do observador |
| `--lon` | `-51.235283` | Longitude do observador |
| `--alt` | `50` | Altitude do observador (metros) |
| `-s`, `--save NOME` | — | Salva o log em `NOME_AAAAMMDD_HHMMSS.log` |
| `--timestamp` | — | Prefixa cada mensagem com timestamp |

### Exemplos de uso

```bash
# Setup básico com localização padrão (Porto Alegre)
python sateliot_quick_test.py --port COM3

# Baud rate customizado
python sateliot_quick_test.py --port COM3 --baud 115200

# Informar localização manualmente
python sateliot_quick_test.py --port COM3 --lat -30.065 --lon -51.235

# Salvar log da sessão com timestamp em cada linha
python sateliot_quick_test.py --port COM3 --save session --timestamp
```

---

## `get_trace.py`

Automatiza a captura de trace LTE (`nrfutil trace lte`) alinhada às passagens previstas dos
satélites LEO. Reaproveita a mesma lógica de previsão de passagens de `leo_next_passes.py`
(buscando os TLEs via `tle_fetcher.py`, com o mesmo fallback CelesTrak → N2YO → SatNOGS), inicia a
captura `--pre` minutos antes do início (*rise*) da passagem e a encerra `--post` minutos após o
pico de elevação, repetindo o ciclo indefinidamente para a próxima passagem.

### Argumentos

| Argumento | Padrão | Descrição |
|---|---|---|
| `--port` | *(obrigatório)* | Porta serial usada pelo `nrfutil` (ex: `COM4` ou `/dev/ttyUSB0`) |
| `--suffix` | `BRA` | Sufixo do nome do arquivo de saída |
| `--pre MIN` | `10` | Minutos antes do *rise* para iniciar a captura |
| `--post MIN` | `10` | Minutos após o pico de elevação para encerrar a captura |
| `-e`, `--min-elevation DEG` | `50` | Elevação mínima (graus) para considerar uma passagem |
| `--lat DEG` | `-30.065361` | Latitude do observador |
| `--lon DEG` | `-51.235283` | Longitude do observador |
| `-s`, `--satellites NOME...` | todos | Satélites a rastrear |
| `--output-dir DIR` | `.` | Diretório de saída dos arquivos de trace |
| `--test` | — | Inicia uma captura imediata de 1 minuto e encerra (modo de teste) |

Os arquivos gerados seguem o padrão `<data_hora_do_pico>_<satélite_abreviado>_<sufixo>.bin`
(ex: `20260618_2130_SIOT2_BRA.bin`).

### Exemplos de uso

```bash
# Testar rapidamente se a captura funciona (1 minuto, sem esperar passagem real)
python get_trace.py --port COM4 --test

# Monitorar passagens continuamente com janelas padrão (10 min antes/depois)
python get_trace.py --port COM4

# Capturar apenas para um satélite específico, com janelas maiores e elevação mínima de 60°
python get_trace.py --port COM4 -s SATELIOT_2 --pre 15 --post 20 -e 60

# Salvar os traces em outro diretório, com sufixo customizado
python get_trace.py --port COM4 --output-dir traces/ --suffix TESTE
```
