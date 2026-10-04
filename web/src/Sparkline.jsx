// Mini-gráfico da rota sem biblioteca de gráfico: um <polyline> já resolve.
const LARGURA = 120;
const ALTURA = 32;

export default function Sparkline({ pontos }) {
  // pontos: [[data, preco], ...] — só o preço importa para o traçado.
  if (!pontos || pontos.length < 2) return null;
  const valores = pontos.map((p) => p[1]);
  const min = Math.min(...valores);
  const max = Math.max(...valores);
  const faixa = max - min || 1;
  const passo = LARGURA / (valores.length - 1);
  const coords = valores
    .map((v, i) => `${i * passo},${ALTURA - ((v - min) / faixa) * ALTURA}`)
    .join(' ');

  return (
    <svg width={LARGURA} height={ALTURA} viewBox={`0 0 ${LARGURA} ${ALTURA}`} aria-hidden="true">
      <polyline points={coords} fill="none" stroke="#0B4F6C" strokeWidth="2" />
    </svg>
  );
}
