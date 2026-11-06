/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        navy: {
          50: '#eef4f8',
          100: '#d9e6ef',
          200: '#b3cddf',
          300: '#84aac6',
          400: '#4d7ea6',
          500: '#2c5f88',
          600: '#17486e',
          700: '#0f3a5c',
          800: '#0b2c4a',
          900: '#0b2c4a',
          950: '#071f36',
        },
        gold: {
          400: '#d4b13a',
          500: '#c9a227',
          600: '#a8871f',
        },
        teal: {
          100: '#d9efee',
          700: '#0e7c7b',
          800: '#0b6362',
        },
      },
      fontFamily: {
        sans: ['Inter', '"IBM Plex Sans Arabic"', 'system-ui', 'sans-serif'],
      },
      boxShadow: {
        sm: '0 1px 2px 0 rgb(11 44 74 / 0.06), 0 1px 3px 0 rgb(11 44 74 / 0.08)',
      },
    },
  },
  plugins: [],
}
