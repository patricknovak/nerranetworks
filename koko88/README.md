# Koko88 Club

A lifestyle brand by Olya — empowering women through fashion, family values, fitness, AI, love, and community.

## Deploying as a Standalone GitHub Pages Site

This directory is self-contained and can be deployed independently:

1. Create a new repository (e.g., `koko88-club`)
2. Copy the contents of this `koko88/` directory to the new repo root
3. Rename `CNAME.example` to `CNAME` and update the domain
4. Enable GitHub Pages in the repo settings (source: root `/`, branch: `main`)
5. Configure DNS for your custom domain to point to GitHub Pages

## Structure

```
index.html              # English landing page
ru/index.html           # Russian landing page
styles/koko88.css       # Brand design system
assets/favicon.svg      # K88 favicon
.nojekyll               # Bypass Jekyll processing
```

## Bilingual

The site is fully bilingual (English/Russian) with language toggle in the navigation.
Each page includes `hreflang` tags for SEO.

## Podcast Integration

The site loads the latest episode of "Finansy Prosto" from the Nerra Network RSS feed.
Update the RSS URL in the `<script>` section if the feed location changes.
