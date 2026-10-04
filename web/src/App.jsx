import { useEffect, useMemo, useState } from 'react';
import { Container, Typography, CircularProgress, Alert, Box, Stack } from '@mui/material';
import Filtros from './Filtros.jsx';
import Oferta from './Oferta.jsx';
import { carregarPrecos, carregarHistorico } from './dados.js';
import { atualizadoHa } from './format.js';

const FILTROS_KEY = 'passagens:filtros';

const FILTROS_PADRAO = {
  precoMax: '',
  destinos: [],
  paradasMax: 'qualquer',
  soPromo: false,
};

function lerLocalStorage(chave, padrao) {
  try {
    const bruto = localStorage.getItem(chave);
    if (!bruto) return padrao;
    return { ...padrao, ...JSON.parse(bruto) };
  } catch {
    return padrao;
  }
}

function gravarLocalStorage(chave, valor) {
  // setItem lança QuotaExceededError (Safari privado, disco cheio) e um throw
  // dentro do efeito derrubaria a árvore inteira: tela branca.
  try {
    localStorage.setItem(chave, JSON.stringify(valor));
  } catch {
    /* não persistido nesta sessão */
  }
}

export default function App() {
  const [status, setStatus] = useState('carregando'); // carregando | ok | erro
  const [dados, setDados] = useState(null);
  const [historico, setHistorico] = useState({});
  const [filtros, setFiltros] = useState(() => lerLocalStorage(FILTROS_KEY, FILTROS_PADRAO));

  useEffect(() => {
    carregarPrecos()
      .then((d) => {
        setDados(d);
        setStatus('ok');
      })
      .catch(() => setStatus('erro'));
    carregarHistorico().then(setHistorico);
  }, []);

  useEffect(() => gravarLocalStorage(FILTROS_KEY, filtros), [filtros]);

  const setups = dados?.setups || [];

  const destinosDisponiveis = useMemo(
    () => [...new Set(setups.flatMap((s) => s.ofertas.map((o) => o.destino)))].sort(),
    [setups],
  );

  const passaFiltro = (oferta) => {
    if (filtros.precoMax !== '' && oferta.preco > Number(filtros.precoMax)) return false;
    if (filtros.destinos.length && !filtros.destinos.includes(oferta.destino)) return false;
    if (filtros.paradasMax !== 'qualquer') {
      if (oferta.paradas == null || oferta.paradas > filtros.paradasMax) return false;
    }
    if (filtros.soPromo && !oferta.promo) return false;
    return true;
  };

  // Setups com as ofertas já filtradas — um card só aparece se sobrar algo.
  const setupsFiltrados = useMemo(
    () =>
      setups
        .map((s) => ({ ...s, ofertas: s.ofertas.filter(passaFiltro) }))
        .filter((s) => s.ofertas.length > 0),
    [setups, filtros],
  );

  // Promoções batidas, juntas no topo — é o que o dono abre a página para ver.
  const promos = useMemo(
    () =>
      setupsFiltrados.flatMap((s) => s.ofertas.filter((o) => o.promo).map((o) => ({ oferta: o, setup: s.nome }))),
    [setupsFiltrados],
  );

  const semSetups = setups.length === 0;
  const semResultadoFiltrado = !semSetups && setupsFiltrados.length === 0;

  return (
    <Container maxWidth="lg" sx={{ py: 3 }}>
      <Typography variant="h1" sx={{ fontSize: { xs: '1.25rem', md: '1.75rem' }, mb: 0.5 }}>
        Radar de passagens
      </Typography>

      {status === 'ok' && (
        <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }} title={dados.gerado_em}>
          {atualizadoHa(dados.gerado_em)} · preços são indicativos: a compra é feita no Google
          Flights e o valor precisa ser confirmado lá antes de pagar.
        </Typography>
      )}

      {status === 'carregando' && (
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 2, py: 4 }}>
          <CircularProgress aria-hidden="true" />
          <Typography>Carregando dados…</Typography>
        </Box>
      )}

      {status === 'erro' && (
        <Alert severity="info">
          Nenhuma coleta ainda — rode o coletor (`coletor/radar.py`) para gerar os dados.
        </Alert>
      )}

      {status === 'ok' && semSetups && (
        <Alert severity="info">A coleta rodou, mas nenhum setup tem oferta ainda.</Alert>
      )}

      {status === 'ok' && !semSetups && (
        <>
          <Filtros
            destinosDisponiveis={destinosDisponiveis}
            filtros={filtros}
            setFiltros={setFiltros}
            onLimpar={() => setFiltros(FILTROS_PADRAO)}
          />

          {promos.length > 0 && (
            <Box sx={{ mb: 3 }}>
              <Typography variant="h2" sx={{ mb: 1 }}>
                Promoções
              </Typography>
              <Stack spacing={1.5}>
                {promos.map(({ oferta, setup }) => (
                  <Box key={oferta.url}>
                    <Typography variant="caption" color="text.secondary">
                      {setup}
                    </Typography>
                    <Oferta oferta={oferta} historico={historico} destaque />
                  </Box>
                ))}
              </Stack>
            </Box>
          )}

          {semResultadoFiltrado ? (
            <Alert severity="info">Nenhuma oferta corresponde aos filtros atuais.</Alert>
          ) : (
            <Stack spacing={3}>
              {setupsFiltrados.map((s) => (
                <Box key={s.nome}>
                  <Typography variant="h2" sx={{ mb: 1 }}>
                    {s.nome}
                    <Typography component="span" variant="body2" color="text.secondary" sx={{ ml: 1 }}>
                      {s.origem} → {s.destino}
                    </Typography>
                  </Typography>
                  <Stack spacing={1.5}>
                    {s.ofertas.map((oferta) => (
                      <Oferta key={oferta.url} oferta={oferta} historico={historico} />
                    ))}
                  </Stack>
                </Box>
              ))}
            </Stack>
          )}
        </>
      )}
    </Container>
  );
}
