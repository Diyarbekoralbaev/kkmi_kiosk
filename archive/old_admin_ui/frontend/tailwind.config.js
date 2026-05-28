/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        bg: '#0a0a0f',
        panel: '#13131a',
        border: '#1e1e2a',
        accent: '#6366f1',
      },
    },
  },
  plugins: [],
}
