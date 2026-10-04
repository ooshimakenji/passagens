// De onde a tela lê os dados.
//
// Em produção eles NÃO estão no build: vivem no branch órfão `dados` do repo,
// servido pelo raw do GitHub (que manda `access-control-allow-origin: *`),
// igual ao `licitacoes`. Assim a coleta diária não redeploya o site e o
// histórico do repositório não engorda a cada dia.
//
// Sem gzip aqui de propósito: o `licitacoes` comprime porque uma UF passa de
// 5 MB; `precos.json` tem poucas centenas de ofertas. Se passar de ~1 MB, copiar
// o `descomprimir` de lá.
const RAW = 'https://raw.githubusercontent.com/ooshimakenji/radar-passagens/dados';

async function buscar(arquivo) {
  // Em dev o arquivo local vem primeiro: dá para rodar o coletor e ver o
  // resultado sem passar pelo GitHub.
  const caminhos = import.meta.env.DEV ? [`data/${arquivo}`, `${RAW}/${arquivo}`] : [`${RAW}/${arquivo}`];
  for (const caminho of caminhos) {
    try {
      const r = await fetch(caminho);
      if (!r.ok) continue;
      return r.json();
    } catch {
      /* tenta o próximo caminho */
    }
  }
  throw new Error(`${arquivo}: não encontrado`);
}

export const carregarPrecos = () => buscar('precos.json');

/// Histórico é opcional (usado só na sparkline da rota): ausência não deve
/// derrubar a tela principal.
export const carregarHistorico = () => buscar('historico.json').catch(() => ({}));
