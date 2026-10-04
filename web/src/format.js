// Formatação pt-BR usada pelos cartões de oferta.

export const moeda = new Intl.NumberFormat('pt-BR', {
  style: 'currency',
  currency: 'BRL',
  maximumFractionDigits: 0,
});

const diaSemanaData = new Intl.DateTimeFormat('pt-BR', {
  weekday: 'short',
  day: '2-digit',
  month: 'short',
});

/// "qui, 07 de jan" — o dia da semana importa numa passagem (voo de terça costuma
/// ser mais barato que de sexta) e o mês abreviado evita confundir 07/01 com
/// 01/07. O pt-BR abrevia com ponto em weekday e month ("qui., 07 de jan."):
/// tira os dois, senão fica sujo.
export function dataCurta(iso) {
  if (!iso) return '—';
  const d = new Date(`${iso}T00:00:00`);
  if (Number.isNaN(d.getTime())) return '—';
  return diaSemanaData.format(d).replaceAll('.', '');
}

export function estadiaDias(ida, volta) {
  if (!ida || !volta) return null;
  const a = new Date(`${ida}T00:00:00`);
  const b = new Date(`${volta}T00:00:00`);
  if (Number.isNaN(a.getTime()) || Number.isNaN(b.getTime())) return null;
  return Math.round((b - a) / 86400000);
}

export function duracaoTexto(min) {
  if (min == null) return null;
  const h = Math.floor(min / 60);
  const m = min % 60;
  return m ? `${h}h ${m}min` : `${h}h`;
}

/// "atualizado há X" é mais lido de relance do que uma data-hora completa —
/// mas a data completa fica sempre disponível no title, para quem quiser.
export function atualizadoHa(iso) {
  if (!iso) return 'nunca atualizado';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return 'nunca atualizado';
  const min = Math.floor((Date.now() - d.getTime()) / 60000);
  if (min < 1) return 'atualizado agora';
  if (min < 60) return `atualizado há ${min} min`;
  const h = Math.floor(min / 60);
  if (h < 24) return `atualizado há ${h}h`;
  const dias = Math.floor(h / 24);
  return `atualizado há ${dias} dia${dias === 1 ? '' : 's'}`;
}
