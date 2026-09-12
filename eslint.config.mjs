// Flat ESLint config baseline.
//
// The dev container installs eslint, @eslint/js, typescript-eslint and globals
// globally (resolvable via NODE_PATH), so linting works before a project has
// its own node_modules. Once the project adds them to package.json, this file
// keeps working unchanged.
import js from '@eslint/js';
import globals from 'globals';
import tseslint from 'typescript-eslint';

export default tseslint.config(
  {
    ignores: ['node_modules/**', 'dist/**', 'build/**', 'coverage/**', '.venv/**', '.terraform/**'],
  },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    languageOptions: {
      ecmaVersion: 'latest',
      sourceType: 'module',
      globals: { ...globals.node, ...globals.es2024 },
    },
    rules: {
      'no-unused-vars': 'off',
      '@typescript-eslint/no-unused-vars': ['warn', { argsIgnorePattern: '^_' }],
      'no-console': 'off',
    },
  },
);
