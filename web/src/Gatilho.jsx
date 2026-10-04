import { useState } from 'react';
import { Box, TextField, Typography, Stack, Button, Collapse, Alert, Link } from '@mui/material';
import NotificationsIcon from '@mui/icons-material/Notifications';
import { moeda } from './format.js';

/// Onde o gatilho de promoção é ajustado sem esperar a próxima coleta.
///
/// São dois gatilhos, e a diferença importa:
///
///   - o daqui recalcula o destaque **na hora**, em cima dos dados já coletados. Mexer no
///     teto e ver o que passa a bater é instantâneo;
///   - o do `config.json` é o que **avisa quando ninguém está olhando** — a página é
///     estática, não roda de madrugada nem abre issue. Só o coletor faz isso.
///
/// Por isso o botão abaixo não "salva": ele abre o `config.json` no editor do GitHub já
/// com o valor que você escolheu aqui para colar. Um site estático não tem como escrever
/// no repositório, e inventar um backend só para isso seria caro demais pelo que entrega.
const REPO_CONFIG = 'https://github.com/ooshimakenji/radar-passagens/edit/main/config.json';

export default function Gatilho({ gatilho, setGatilho, doColetor, quantosBatem }) {
  const [aberto, setAberto] = useState(false);
  const set = (campo) => (e) => {
    const v = e.target.value;
    setGatilho((g) => ({ ...g, [campo]: v === '' ? '' : Number(v) }));
  };

  const difere =
    (gatilho.teto !== '' && gatilho.teto !== doColetor?.teto_brl) ||
    (gatilho.pct !== '' && gatilho.pct !== doColetor?.pct_abaixo_mediana);

  return (
    <Box
      component="fieldset"
      sx={{ border: '1px solid', borderColor: 'divider', borderRadius: 2, p: 2, m: 0, mb: 2 }}
    >
      <Typography component="legend" variant="h2" sx={{ fontSize: '1.1rem' }}>
        Meu gatilho de promoção
      </Typography>

      <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2} alignItems={{ sm: 'center' }}>
        <TextField
          label="Teto (R$)"
          type="number"
          value={gatilho.teto}
          onChange={set('teto')}
          helperText="Abaixo disso é promoção"
          sx={{ flex: 1 }}
          inputProps={{ min: 0, step: 100 }}
        />
        <TextField
          label="% abaixo da mediana"
          type="number"
          value={gatilho.pct}
          onChange={set('pct')}
          helperText="Queda forte para o padrão da rota"
          sx={{ flex: 1 }}
          inputProps={{ min: 0, max: 90, step: 5 }}
        />
        <Typography variant="body2" color="text.secondary" sx={{ flex: 1 }}>
          {quantosBatem === 0
            ? 'Nenhuma oferta coletada bate esse gatilho hoje.'
            : `${quantosBatem} oferta${quantosBatem === 1 ? '' : 's'} bate${
                quantosBatem === 1 ? '' : 'm'
              } esse gatilho agora.`}
        </Typography>
      </Stack>

      <Collapse in={difere}>
        <Alert
          severity="info"
          icon={<NotificationsIcon />}
          sx={{ mt: 2 }}
          action={
            <Button
              size="small"
              component={Link}
              href={REPO_CONFIG}
              target="_blank"
              rel="noopener"
              sx={{ minHeight: 44 }}
              onClick={() => setAberto(true)}
            >
              Editar config
            </Button>
          }
        >
          Isto muda só o que você vê aqui. Para ser <strong>avisado</strong> com esse gatilho
          (inclusive de madrugada, sem abrir a página), o valor precisa ir para o{' '}
          <code>config.json</code>:{' '}
          <code>
            {'"gatilho": { '}
            {gatilho.teto !== '' && `"teto_brl": ${gatilho.teto}`}
            {gatilho.teto !== '' && gatilho.pct !== '' && ', '}
            {gatilho.pct !== '' && `"pct_abaixo_mediana": ${gatilho.pct}`}
            {' }'}
          </code>
          {doColetor?.teto_brl != null && (
            <>
              {' '}
              (hoje o alerta dispara em {moeda.format(doColetor.teto_brl)})
            </>
          )}
        </Alert>
      </Collapse>
      {aberto && (
        <Typography variant="caption" color="text.secondary" component="div" sx={{ mt: 1 }}>
          Depois de salvar no GitHub, a próxima coleta já usa o gatilho novo.
        </Typography>
      )}
    </Box>
  );
}
