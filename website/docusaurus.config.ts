import {themes as prismThemes} from 'prism-react-renderer';
import type {Config} from '@docusaurus/types';
import type * as Preset from '@docusaurus/preset-classic';

// This runs in Node.js - Don't use client-side code here (browser APIs, JSX...)

const config: Config = {
  title: 'Energex',
  tagline: 'A bitemporal, point-in-time data platform for power markets',
  favicon: 'img/favicon.ico',

  future: {
    v4: true, // Improve compatibility with the upcoming Docusaurus v4
  },

  url: 'https://oldhero5.github.io',
  // Project Pages site: served at https://oldhero5.github.io/energex/
  baseUrl: '/energex/',

  organizationName: 'oldhero5',
  projectName: 'energex',

  onBrokenLinks: 'throw',

  markdown: {
    hooks: {
      onBrokenMarkdownLinks: 'warn',
    },
  },

  i18n: {
    defaultLocale: 'en',
    locales: ['en'],
  },

  presets: [
    [
      'classic',
      {
        docs: {
          sidebarPath: './sidebars.ts',
          routeBasePath: '/', // serve the docs at the site root
          editUrl: 'https://github.com/oldhero5/energex/tree/main/website/',
        },
        blog: false,
        theme: {
          customCss: './src/css/custom.css',
        },
      } satisfies Preset.Options,
    ],
  ],

  themeConfig: {
    image: 'img/docusaurus-social-card.jpg',
    colorMode: {
      respectPrefersColorScheme: true,
    },
    navbar: {
      title: 'Energex',
      logo: {
        alt: 'Energex',
        src: 'img/logo.svg',
      },
      items: [
        {
          type: 'docSidebar',
          sidebarId: 'docsSidebar',
          position: 'left',
          label: 'Documentation',
        },
        {
          href: 'https://github.com/oldhero5/energex',
          label: 'GitHub',
          position: 'right',
        },
      ],
    },
    footer: {
      style: 'dark',
      links: [
        {
          title: 'Docs',
          items: [
            {label: 'Introduction', to: '/'},
            {label: 'Architecture', to: '/architecture'},
            {label: 'Quickstart', to: '/quickstart'},
            {label: 'Roadmap', to: '/roadmap'},
          ],
        },
        {
          title: 'Project',
          items: [
            {label: 'GitHub', href: 'https://github.com/oldhero5/energex'},
            {
              label: 'License (PolyForm Noncommercial 1.0.0)',
              href: 'https://polyformproject.org/licenses/noncommercial/1.0.0/',
            },
          ],
        },
      ],
      copyright: `Copyright © ${new Date().getFullYear()} Marty Harris. Source-available under the PolyForm Noncommercial License 1.0.0. Built with Docusaurus.`,
    },
    prism: {
      theme: prismThemes.github,
      darkTheme: prismThemes.dracula,
    },
  } satisfies Preset.ThemeConfig,
};

export default config;
