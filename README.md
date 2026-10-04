# Radar de Passagens

Vigia passagens aéreas e **avisa quando o preço cai**, com um guarda-chuva que nenhum
alerta pronto cobre: *"São Paulo → qualquer cidade do Japão, em janeiro, estadia de 10 a 20
dias, abaixo de R$ 6.000"*.

**Coletor em Python** roda no GitHub Actions todo dia às 7h (BRT) e publica `precos.json`,
`historico.json` e `rotas_mortas.json` no branch órfão `dados`. **Dashboard React + MUI**
lê esses arquivos pelo raw do GitHub — a coleta diária não redeploya o site. Sem servidor,
sem banco. Mesmo desenho do [`licitacoes`](../licitacoes).

> O `RAW` em `web/src/dados.js` aponta para `ooshimakenji/passagens`. Se o repo for criado
> com outro nome, é lá que se ajusta.

## Por que existe, se o Google Flights é melhor que isso

É melhor, e a compra deve ser feita lá — ele valida a tarifa antes de exibir. Mas o alerta
dele (e o do Skyscanner) tem três limites que este projeto existe para furar:

| | Google Flights / Skyscanner | aqui |
|---|---|---|
| alerta com **destino variável** | não — exige destino fixo | **sim**: um país inteiro |
| **quem decide** o que é promo | o Google, por critério opaco | **você**: teto em R$ ou % abaixo da mediana |
| **série histórica** da rota | não entrega | **sua**, em JSON |

O preço coletado é **sinal para ir conferir**, nunca a verdade final. Cada oferta vem com o
link da busca no Google Flights.

## Uso

```bash
pip install -r coletor/requirements.txt
cd coletor && python test_radar.py   # verificação, sem rede
python radar.py                      # coleta (MAX_BUSCAS=5 para testar rápido)

cd ../web && npm install && npm run dev
```

## Os setups (`config.json`)

```json
{ "nome": "Japão — qualquer cidade",
  "origem": "SAO", "destino": "JP",
  "meses": ["2027-01"], "estadia_dias": [10, 20],
  "max_paradas": 2, "top_destinos": 5,
  "gatilho": { "teto_brl": 6000, "pct_abaixo_mediana": 25 } }
```

| campo | efeito |
|---|---|
| `origem` / `destino` | **3 letras** = aeroporto ou cidade (`SAO` já cobre GRU+CGH+VCP, `TYO` cobre HND+NRT numa busca só); **2 letras** = país, expandido pelo radar; **lista** = cada item pela mesma regra, então `["JP","KR","TW"]` compara Japão, Coreia e Taiwan no mesmo painel |
| `stopover` | `{"em": ["ICN","DOH"], "dias": [2,5], "datas": 2}` — parada de dias no meio do caminho (ver abaixo) |
| `meses` | `AAAA-MM`; datas passadas são ignoradas |
| `estadia_dias` | faixa `[min, max]`; o radar amostra mínimo, meio e máximo |
| `top_destinos` | quantas cidades do país seguem para a varredura completa (ver sondagem) |
| `gatilho.teto_brl` | dispara em `preço <= teto`. Único critério que funciona na primeira execução |
| `gatilho.pct_abaixo_mediana` | dispara em `preço <= mediana * (1 - pct/100)`. Precisa de 3 coletas da rota |

Qualquer um dos dois critérios basta; omitir um desliga aquele critério. Gatilho vazio
nunca dispara.

Globais: `passo_dias` (de quantos em quantos dias varrer as idas), `max_cidades` (0 = todas
as do país), `max_buscas_por_execucao`, `pausa_segundos`, `historico_dias`.

## Como "qualquer cidade do país" funciona

O Google Flights **não aceita país** como destino — `SAO→JP` devolve zero resultados. E
adivinhar quais cidades importam não funciona: a OurAirports marca **28** aeroportos
japoneses como `large_airport`, então porte não desempata e Tóquio ficava fora de um top 6
alfabético.

Então quem desempata é o preço, em duas fases:

1. **sonda** — uma busca por cidade do país, numa data representativa (o meio do período).
   Cidade que o Google não cota a partir da sua origem cai fora sozinha.
2. **varredura** — todas as combinações de data só nas `top_destinos` cidades mais baratas
   da sonda.

As sondas são preços reais e entram no resultado; nada se joga fora.

### A parte chata: resposta vazia não quer dizer "não tem voo"

O Google às vezes devolve a página **sem** os resultados, e o HTML é idêntico ao de uma
rota que realmente não existe — sem nenhum "no flights found" para distinguir. Medido em
2026-10-04: numa sonda de 72 cidades, `SAO→TYO` voltou vazio; consultado sozinho em
seguida, deu R$ 7.690 **seis vezes seguidas**. Tóquio tinha sido descartada por engano.

Então:

- `consultar()` **repete** quando vem vazio (`tentativas=2`, com espera crescente);
- rota que vem vazia **3 execuções seguidas** descansa 30 dias (`rotas_mortas.json`).
  Sem isso, o retry custaria 3 buscas diárias em cada uma das ~64 cidades japonesas que
  de fato não têm ligação com São Paulo. Achar preço ressuscita a rota na hora.

Esse par (repetir + esquecer o que está morto) é o que separa um radar que serve de um que
te diz "não achei voo para Tóquio".

## Parar no meio do caminho

Numa viagem de 24h faz sentido quebrar o trajeto. Duas formas, de custo bem diferente:

**1. Escala longa — sai de graça.** O rótulo do Google já descreve cada escala
(`Layover (1 of 1) is a 2 hr 45 min layover at John F. Kennedy International Airport in
New York`). O radar lê isso **sem nenhuma busca extra** e marca a oferta quando alguma
escala passa de `escala_min_horas` (padrão **8h** — abaixo disso não dá para sair, passar
imigração e voltar sem correr).

**2. Stopover de dias — dois bilhetes.** O multi-city do Google **não serve**: a página de
`trip="multi-city"` volta sem resultado no HTML, 5 tentativas de 5, com tamanho idêntico
(não é a intermitência descrita acima — simplesmente não vem). Então o roteiro é montado
como as pessoas de fato compram:

```
bilhete 1: SAO ↔ ICN   (ida e volta nas datas do período)
bilhete 2: ICN ↔ TYO   (sai N dias depois de chegar, volta N dias antes)
```

Você passa pelo hub na ida **e** na volta, e o trecho asiático curto costuma ser dominado
por low-cost — às vezes o conjunto sai perto ou abaixo do voo direto. Em troca são **dois
contratos separados**: atraso no primeiro não obriga ninguém a reacomodar no segundo. A
tela avisa isso em cada oferta de stopover, e mostra a diferença contra o voo direto que
serviu de base — o número só significa algo comparado.

Para não explodir: o stopover é cotado **só sobre as melhores ofertas que a varredura já
achou** (`datas`, padrão 2), e o bilhete 1 não depende de `dias`, então é cacheado por
(hub, par de datas).

## O alerta

Quando um setup dispara, o job **abre uma issue neste repo** — o GitHub já notifica por
e-mail e no app do celular. Sem bot de Telegram, sem SMTP, sem secret além do
`GITHUB_TOKEN` que o Actions já dá. Rodando local (sem `GITHUB_ACTIONS`), só imprime no
terminal.

## De onde vêm os dados

| fonte | para quê | custo |
|---|---|---|
| Google Flights (HTML) | preço, companhia, escalas, duração | grátis, sem chave |
| [`fast-flights`](https://github.com/AWeirdDev/flights) (MIT) | monta a URL protobuf e faz o fetch | — |
| [Travelpayouts](https://api.travelpayouts.com/data/en/airports.json) | código de **cidade** IATA | grátis, sem token |
| [OurAirports](https://davidmegginson.github.io/ourairports-data/) (CC0) | porte do aeroporto e se tem voo regular | grátis |

### A lista completa (`tfu`)

Sem o parâmetro `tfu=EgQIABABIgA` o Google devolve **só o topo** da lista. Medido em
2026-10-04, mesma busca: SAO→TYO foi de **11 para 96** itinerários, SAO→PVG de **13 para
48**. O mais barato não mudou nessas rotas, mas as opções com escala ≥8h foram de 0 para
23 — é a diferença entre "existe uma passada por Paris de 14h" e não saber disso.

O parâmetro foi perdido no rewrite 3.0 do `fast-flights` e restaurado no
[PR #115](https://github.com/AWeirdDev/flights/pull/115), mas o PyPI ainda publica a 3.1.0
sem ele — por isso `radar.py` monta a requisição com o `primp` (que já vem com a lib) em
vez de usar o `fetch_flights_html`.

**O que nem o `tfu` resolve:** companhias **chinesas**. Em SAO→PVG, 48 itinerários e
nenhum da China Eastern, Air China ou China Southern. Não é truncamento, é ausência — para
tarifa chinesa seria preciso outra fonte (Trip.com), ainda não avaliada.

**O parser do `fast-flights` não é usado.** Ele ancora em classe CSS (`kw4HXCc5QE=`), que o
Google reescreve a cada deploy: em 2026-10-04 a versão 3.1.0 devolveu **0 voos** para
JFK→LAX com o HTML chegando intacto. `coletor/extrator.py` lê o `aria-label`, que é
contrato de acessibilidade — mexer nele quebra leitor de tela, então muda raramente. É o
mesmo defeito de todos os trackers de voo que testei.

### Fontes avaliadas e descartadas

- **Amadeus Self-Service**: encerrado em 17/07/2026. **Kiwi Tequila**: fechado para novos devs.
- **Travelpayouts Data API** (preços): exige token e serve **cache** de buscas de outros
  usuários — mesmo tipo de dado do calendário do Skyscanner, que não atualiza ao vivo. Fica
  como plano B se o IP do Actions for bloqueado.
- **Trackers prontos** (`ticket-tracker`, `FlightsPricingTracker`, `GFScraper`): 0 a 2
  estrelas e todos Next.js + Prisma + servidor — o oposto de um JSON commitado.
