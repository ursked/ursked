// Next 16 removed `next lint`; ESLint 9 uses flat config. eslint-config-next@16
// ships a native flat-config array (next core-web-vitals + next/typescript), so
// we spread it directly — no FlatCompat bridge needed.
import next from 'eslint-config-next';

const config = [
  ...next,
  { ignores: ['.next/**', 'node_modules/**', 'next-env.d.ts'] },
];

export default config;
