import { Box, Paper, Typography, Chip, Stack, Link } from '@mui/material';
import OpenInNewIcon from '@mui/icons-material/OpenInNew';
import ScienceIcon from '@mui/icons-material/Science';
import Sparkline from './Sparkline.jsx';
import { MONO, ALVO_TOQUE } from './theme.js';
import { moeda, dataCurta, estadiaDias, duracaoTexto } from './format.js';

/// Um cartão de oferta. `destaque` pinta o cartão quando é uma promoção batida
/// — essa é a prioridade visual nº 1 da tela (é o que o dono abre para ver).
export default function Oferta({ oferta, destaque = false, historico }) {
  const dias = estadiaDias(oferta.ida, oferta.volta);
  const duracao = duracaoTexto(oferta.duracao_min);
  const chave = `${oferta.origem}-${oferta.destino}`;
  const pontos = historico?.[chave];

  return (
    <Paper
      variant="outlined"
      sx={{
        p: 2,
        ...(destaque && {
          borderColor: 'success.main',
          borderWidth: 2,
          bgcolor: '#F0F8F2',
        }),
      }}
    >
      <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2} alignItems={{ sm: 'center' }}>
        <Box sx={{ minWidth: 140 }}>
          <Typography sx={{ fontFamily: MONO, fontWeight: 600, fontSize: '1.75rem', lineHeight: 1 }}>
            {moeda.format(oferta.preco)}
          </Typography>
          <Typography variant="caption" color="text.secondary">
            ida e volta, 1 adulto
          </Typography>
        </Box>

        <Box sx={{ flex: 1, minWidth: 0 }}>
          <Typography sx={{ fontWeight: 500 }}>
            {oferta.origem} → {oferta.destino}
            {oferta.sonda && (
              <Chip
                icon={<ScienceIcon fontSize="small" />}
                label="sondagem"
                size="small"
                variant="outlined"
                color="warning"
                sx={{ ml: 1, verticalAlign: 'middle' }}
              />
            )}
          </Typography>
          <Typography variant="body2" color="text.secondary" sx={{ fontFamily: MONO }}>
            {dataCurta(oferta.ida)} → {dataCurta(oferta.volta)}
            {dias != null && ` · ${dias} dia${dias === 1 ? '' : 's'} de estadia`}
          </Typography>
          <Typography variant="body2" color="text.secondary">
            {[oferta.cia, oferta.paradas == null ? null : oferta.paradas === 0 ? 'sem paradas' : `${oferta.paradas} parada${oferta.paradas === 1 ? '' : 's'}`, duracao]
              .filter(Boolean)
              .join(' · ') || 'detalhes do voo não informados'}
          </Typography>

          {oferta.escala_longa && (
            <Typography variant="body2" sx={{ color: 'info.main', fontWeight: 500, mt: 0.5 }}>
              {duracaoTexto(oferta.escala_longa.duracao_min)} de escala em{' '}
              {oferta.escala_longa.cidade || oferta.escala_longa.aeroporto} — dá para sair do
              aeroporto
            </Typography>
          )}

          {oferta.stopover && (
            <Box sx={{ mt: 0.5 }}>
              <Typography variant="body2" sx={{ fontWeight: 500 }}>
                {oferta.stopover.dias_no_hub} dias em {oferta.stopover.hub} no caminho
                {/* O número só diz algo comparado ao voo direto que serviu de base. */}
                {oferta.stopover.base_preco != null && (
                  <Typography component="span" variant="body2" color="text.secondary">
                    {' '}
                    ({oferta.preco > oferta.stopover.base_preco ? '+' : '−'}
                    {moeda.format(Math.abs(oferta.preco - oferta.stopover.base_preco))} vs o
                    voo direto)
                  </Typography>
                )}
              </Typography>
              {oferta.stopover.pernas?.map((p) => (
                <Typography key={p.trecho} variant="caption" color="text.secondary" component="div">
                  {p.trecho} · {dataCurta(p.ida)} → {dataCurta(p.volta)} · {moeda.format(p.preco)}
                  {p.cia ? ` · ${p.cia}` : ''} ·{' '}
                  <Link href={p.url} target="_blank" rel="noopener">
                    ver
                  </Link>
                </Typography>
              ))}
              <Typography variant="caption" sx={{ color: 'warning.main' }} component="div">
                São dois bilhetes separados: atraso no primeiro não obriga ninguém a
                reacomodar você no segundo.
              </Typography>
            </Box>
          )}

          {destaque && oferta.motivo && (
            <Typography variant="body2" sx={{ color: 'success.main', fontWeight: 500, mt: 0.5 }}>
              {oferta.motivo}
            </Typography>
          )}
          {oferta.mediana == null && (
            <Typography variant="caption" color="text.secondary" component="div">
              sem histórico ainda
            </Typography>
          )}
        </Box>

        {pontos && pontos.length > 1 && <Sparkline pontos={pontos} />}

        <Link
          href={oferta.url}
          target="_blank"
          rel="noopener"
          sx={{ display: 'inline-flex', alignItems: 'center', gap: 0.5, minHeight: ALVO_TOQUE, whiteSpace: 'nowrap' }}
        >
          Ver no Google Flights <OpenInNewIcon fontSize="inherit" aria-hidden="true" />
        </Link>
      </Stack>
    </Paper>
  );
}
