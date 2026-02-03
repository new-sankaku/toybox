/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    './index.html',
    './src/**/*.{js,ts,jsx,tsx}'
  ],
  theme: {
    extend: {
      colors: {
        nier: {
          // Background colors
          'bg-main': '#E8E4D4',
          'bg-panel': '#DAD5C3',
          'bg-selected': '#CCC7B5',
          'bg-header': '#57534A',
          'bg-footer': '#57534A',
          // Text colors
          'text-main': '#454138',
          'text-light': '#5A5548',
          'text-header': '#E8E4D4',
          'text-footer': '#E8E4D4',
          // Accent colors (category markers)
          'accent-red': '#B85C5C',
          'accent-orange': '#C4956C',
          'accent-green': '#7AAA7A',
          'accent-blue': '#6B8FAA',
          // Borders
          'border-light': 'rgba(69, 65, 56, 0.2)',
          'border-dark': 'rgba(69, 65, 56, 0.4)'
        }
      },
      fontFamily: {
        'nier': ['"Noto Sans JP"', 'sans-serif']
      },
      letterSpacing: {
        'nier-tight': '0.02em',
        'nier': '0.05em',
        'nier-wide': '0.08em',
        'nier-extra-wide': '0.15em'
      },
      fontSize: {
        'nier-display': '28px',
        'nier-h1': '20px',
        'nier-h2': '16px',
        'nier-body': '14px',
        'nier-small': '13px',
        'nier-caption': '12px'
      },
      borderRadius: {
        'nier': '0'
      },
      boxShadow: {
        'nier-sm': 'var(--shadow-sm)',
        'nier-md': 'var(--shadow-md)',
        'nier-lg': 'var(--shadow-lg)',
        'nier-xl': 'var(--shadow-xl)'
      },
      transitionTimingFunction: {
        'nier-smooth': 'cubic-bezier(0.4, 0.0, 0.2, 1)',
        'nier-decelerate': 'cubic-bezier(0.0, 0.0, 0.2, 1)',
        'nier-accelerate': 'cubic-bezier(0.4, 0.0, 1, 1)'
      },
      transitionDuration: {
        'nier-fast': '150ms',
        'nier-normal': '300ms',
        'nier-slow': '500ms'
      },
      animation: {
        'nier-pulse': 'nier-pulse 2s ease-in-out infinite',
        'nier-fade-in': 'nier-fade-in 0.3s ease-out',
        'nier-slide-in': 'nier-slide-in 0.3s ease-out',
        'nier-slide-in-right': 'nier-slide-in-right 0.3s ease-out'
      },
      keyframes: {
        'nier-pulse': {
          '0%, 100%': { opacity: '1' },
          '50%': { opacity: '0.6' }
        },
        'nier-fade-in': {
          '0%': { opacity: '0' },
          '100%': { opacity: '1' }
        },
        'nier-slide-in': {
          '0%': { opacity: '0', transform: 'translateX(-10px)' },
          '100%': { opacity: '1', transform: 'translateX(0)' }
        },
        'nier-slide-in-right': {
          '0%': { opacity: '0', transform: 'translateX(100%)' },
          '100%': { opacity: '1', transform: 'translateX(0)' }
        }
      },
      spacing: {
        'nier-xs': '4px',
        'nier-sm': '8px',
        'nier-md': '16px',
        'nier-lg': '24px',
        'nier-xl': '32px',
        'sidebar-collapsed': 'var(--sidebar-width-collapsed)',
        'sidebar-expanded': 'var(--sidebar-width-expanded)'
      },
      maxHeight: {
        'log-panel': 'var(--log-panel-max-height)',
        'sequence-panel': 'var(--sequence-panel-max-height)'
      }
    }
  },
  plugins: []
}
