import { createTheme } from '@mui/material/styles';

// Paleta MD3 própria — NÃO usar as cores default do MUI (#1976d2 sobre branco
// dá 4.6:1, reprova em AAA). Contraste calculado com a fórmula de luminância
// relativa da WCAG (https://www.w3.org/TR/WCAG21/#dfn-relative-luminance).
// Todos os pares abaixo ficam >= 7:1 para texto normal (AAA 1.4.6) ou >= 4.5:1
// quando é só ícone/borda grande. Mesma paleta do projeto `licitacoes` —
// já verificada, sem motivo para recalcular.

const bg = '#F5F7FA'; // fundo padrão da página
const paper = '#FFFFFF'; // fundo de cartões

/// Face dos números: preço, data e duração. Algarismo de largura fixa é o que
/// permite comparar preços de olho, descendo a lista de ofertas.
export const MONO = '"IBM Plex Mono", ui-monospace, "Cascadia Mono", monospace';

/// Altura mínima de alvo no toque. A AAA pede 44 (2.5.5) e o Material 3
/// recomenda 48 — no celular vale o maior dos dois.
export const ALVO_TOQUE = 48;

export const theme = createTheme({
  palette: {
    background: { default: bg, paper },
    primary: {
      // #0B4F6C sobre #FFFFFF = 8.94:1 · sobre #F5F7FA = 8.33:1 (ambos >7:1)
      main: '#0B4F6C',
      contrastText: '#FFFFFF', // branco sobre #0B4F6C = 8.94:1
    },
    text: {
      primary: '#1A1C1E', // sobre #FFFFFF = 17.09:1
      secondary: '#3A4750', // sobre #FFFFFF = 9.56:1 (pedido: secondary >= 7:1)
    },
    error: {
      main: '#7A0C1E', // sobre #FFFFFF = 11.06:1
    },
    success: {
      // promoção batida — #0F5C2E sobre #FFFFFF = 8.11:1
      main: '#0F5C2E',
    },
    warning: {
      // sondagem / aviso — #7A4A00 sobre #FFFFFF = 7.48:1
      main: '#7A4A00',
    },
    divider: '#C6CCD1', // borda decorativa, não carrega estado sozinha
  },
  shape: { borderRadius: 8 },
  typography: {
    fontFamily: '"IBM Plex Sans", "Segoe UI", Roboto, Arial, sans-serif',
    h1: { fontSize: '1.75rem', fontWeight: 600, letterSpacing: '-0.02em' },
    h2: { fontSize: '1.1rem', fontWeight: 600 },
    button: { textTransform: 'none', fontWeight: 500 },
  },
  components: {
    MuiCssBaseline: {
      styleOverrides: {
        // AAA 2.4.7 foco visível: outline 3px, deslocado para cair sobre o
        // fundo claro ao redor do elemento (funciona atrás de botões
        // escuros também, já que o outline nasce fora da caixa).
        '*:focus-visible': {
          outline: '3px solid #0B4F6C',
          outlineOffset: '2px',
        },
        '@media (prefers-reduced-motion: reduce)': {
          '*, *::before, *::after': {
            animationDuration: '0.001ms !important',
            animationIterationCount: '1 !important',
            transitionDuration: '0.001ms !important',
            scrollBehavior: 'auto !important',
          },
        },
      },
    },
    MuiButtonBase: {
      defaultProps: { disableRipple: false },
      styleOverrides: {
        root: {
          minWidth: 44,
          minHeight: 44, // AAA 2.5.5 alvo de toque
          '&:focus-visible': { outline: '3px solid #0B4F6C', outlineOffset: 2 },
        },
      },
    },
    MuiIconButton: {
      styleOverrides: { root: { minWidth: 44, minHeight: 44 } },
    },
    MuiOutlinedInput: {
      styleOverrides: {
        // Default do MUI é rgba(0,0,0,0.23) = 1.74:1, reprova em 1.4.11
        // (contorno de componente precisa de 3:1). #6B7480 = 4.6:1.
        notchedOutline: { borderColor: '#6B7480' },
        // 16px é o mínimo que o iOS aceita sem dar zoom automático no campo
        // ao focar — abaixo disso a página inteira salta a cada toque.
        input: { fontSize: 16 },
      },
    },
    MuiChip: {
      styleOverrides: {
        root: { '@media (pointer: coarse)': { minHeight: ALVO_TOQUE } },
      },
    },
  },
});
