/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        kk: {
          blue: '#008eb7',
          blueLight: '#40b0e0',
          green: '#209c3a',
          yellow: '#f7bd29',
          bg: '#f5f8fc',
          bgAlt: '#e8eff6',
          ink: '#0a1628',
          inkSoft: '#3a4a5d',
        },
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif'],
      },
    },
  },
  plugins: [],
}
