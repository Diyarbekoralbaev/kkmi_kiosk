/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        brand: {
          DEFAULT: '#0a4d8c',
          dark: '#073966',
          50: '#eef4fb',
          100: '#dbe7f3',
          200: '#b1c9e3',
          500: '#0a4d8c',
          600: '#093f73',
          700: '#073966',
        },
        accent: {
          DEFAULT: '#f5b932',
          dark: '#d99b18',
          50: '#fdf6e1',
          100: '#fbecbf',
          200: '#f5d97a',
        },
        surface: '#f4f7fb',
        card: '#ffffff',
        ink: {
          DEFAULT: '#1a2740',
          muted: '#5a6b85',
        },
        line: '#e2e8f0',
        tile: '#e8eff7',
        'tile-accent': '#fdf1d4',
        danger: '#dc2626',
        success: '#10b981',
      },
      borderRadius: {
        card: '14px',
        tile: '22px',
        pill: '999px',
      },
      fontFamily: {
        sans: [
          'Inter',
          'ui-sans-serif',
          'system-ui',
          '-apple-system',
          'Segoe UI',
          'Roboto',
          'sans-serif',
        ],
      },
      boxShadow: {
        card: '0 1px 2px 0 rgb(15 23 42 / 0.04)',
        focus: '0 0 0 3px rgb(10 77 140 / 0.18)',
      },
    },
  },
  plugins: [],
}
