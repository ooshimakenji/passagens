import {
  Autocomplete,
  TextField,
  ToggleButton,
  ToggleButtonGroup,
  Button,
  Stack,
  Box,
  Typography,
  FormControlLabel,
  Checkbox,
} from '@mui/material';
import ClearIcon from '@mui/icons-material/Clear';

export default function Filtros({ destinosDisponiveis, filtros, setFiltros, onLimpar }) {
  const set = (campo) => (valor) => setFiltros((f) => ({ ...f, [campo]: valor }));

  return (
    <Box
      component="fieldset"
      sx={{ border: '1px solid', borderColor: 'divider', borderRadius: 2, p: 2, m: 0, mb: 3 }}
    >
      <Typography component="legend" variant="h2" sx={{ fontSize: '1.1rem' }}>
        Filtros
      </Typography>

      <Stack spacing={2}>
        <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2}>
          <TextField
            label="Preço máximo (R$)"
            type="number"
            value={filtros.precoMax}
            onChange={(e) => set('precoMax')(e.target.value)}
            sx={{ flex: 1 }}
            inputProps={{ min: 0 }}
          />
          <Autocomplete
            multiple
            options={destinosDisponiveis}
            value={filtros.destinos}
            onChange={(_, v) => set('destinos')(v)}
            sx={{ flex: 1, minWidth: 180 }}
            renderInput={(params) => <TextField {...params} label="Destino" placeholder="Todos" />}
          />
          <Box role="group" aria-label="Número máximo de paradas">
            <Typography variant="body2" color="text.secondary" sx={{ mb: 0.5 }}>
              Paradas
            </Typography>
            <ToggleButtonGroup
              value={filtros.paradasMax}
              exclusive
              onChange={(_, v) => v !== null && set('paradasMax')(v)}
              size="small"
            >
              <ToggleButton value="qualquer" sx={{ minHeight: 44, px: 2 }}>
                Qualquer
              </ToggleButton>
              <ToggleButton value={0} sx={{ minHeight: 44, px: 2 }}>
                Direto
              </ToggleButton>
              <ToggleButton value={1} sx={{ minHeight: 44, px: 2 }}>
                Até 1
              </ToggleButton>
              <ToggleButton value={2} sx={{ minHeight: 44, px: 2 }}>
                Até 2
              </ToggleButton>
            </ToggleButtonGroup>
          </Box>
        </Stack>

        <Stack direction="row" alignItems="center" justifyContent="space-between">
          <FormControlLabel
            control={
              <Checkbox checked={filtros.soPromo} onChange={(e) => set('soPromo')(e.target.checked)} />
            }
            label="Só promoções (bateram o gatilho)"
          />
          <Button onClick={onLimpar} startIcon={<ClearIcon />} variant="outlined" sx={{ minHeight: 44 }}>
            Limpar filtros
          </Button>
        </Stack>
      </Stack>
    </Box>
  );
}
