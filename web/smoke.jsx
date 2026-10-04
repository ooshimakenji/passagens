/* Renderiza a tela inteira fora do navegador e falha se algo quebrar.
 *
 * `vite build` compila mesmo com `moeda is not defined` — erro de import só aparece
 * quando o componente roda, e foi exatamente esse o bug que passou batido. Aqui a árvore
 * é renderizada de verdade, com dados no formato que o coletor produz.
 *
 *   npm run smoke
 */
import { renderToString } from 'react-dom/server';
import App from './src/App.jsx';
import { avaliar } from './src/App.jsx';

// A tela lê localStorage no estado inicial e faz fetch no efeito; fora do navegador não
// existe nenhum dos dois. useEffect não roda no renderToString, então basta o storage.
globalThis.localStorage = { getItem: () => null, setItem: () => {} };

const html = renderToString(<App />);
if (!html.includes('Radar de passagens')) {
  throw new Error('a tela renderizou sem o título');
}

// O gatilho do front precisa decidir igual ao do coletor (`disparou`, em radar.py),
// senão a tela diz uma coisa e a notificação diz outra.
const oferta = { preco: 7000, mediana: 10000 };
const casos = [
  [{ teto: 7500, pct: '' }, true, 'abaixo do teto'],
  [{ teto: 6500, pct: '' }, false, 'acima do teto'],
  [{ teto: '', pct: 25 }, true, '30% abaixo da mediana passa no critério de 25%'],
  [{ teto: '', pct: 35 }, false, '30% não alcança 35%'],
  [{ teto: '', pct: '' }, false, 'gatilho vazio nunca dispara'],
];
for (const [gatilho, esperado, porque] of casos) {
  const { promo } = avaliar(oferta, gatilho);
  if (promo !== esperado) throw new Error(`gatilho ${JSON.stringify(gatilho)}: ${porque}`);
}

// Sem mediana, o critério percentual não pode opinar.
if (avaliar({ preco: 1, mediana: null }, { teto: '', pct: 90 }).promo) {
  throw new Error('sem histórico, o percentual não deveria disparar');
}

console.log('smoke ok: tela renderiza e o gatilho do front decide como o coletor');
