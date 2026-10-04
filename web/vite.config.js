import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  base: './',
  plugins: [react()],
  // `npm run smoke` renderiza a tela no Node. Sem empacotar as dependências, o Node
  // tropeça nos imports de diretório do MUI (ERR_UNSUPPORTED_DIR_IMPORT). Só afeta o
  // build do smoke; o build do site não usa SSR.
  ssr: { noExternal: true },
});
