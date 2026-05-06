# BP Doctor Landing Page - Deployment Guide

## Quick Start (Local Preview)
Open `index.html` in any browser. Everything is self-contained in one file.

---

## GitHub Pages Deployment

### Step 1: Create the Repository
```bash
cd landing-page
git init
git add .
git commit -m "Initial landing page"
gh repo create bpdoctor-site --public --source=. --push
```

### Step 2: Enable GitHub Pages
1. Go to `github.com/YOUR_USERNAME/bpdoctor-site/settings/pages`
2. Source: **Deploy from a branch**
3. Branch: `main`, folder: `/ (root)`
4. Click **Save**
5. Site will be live at `https://YOUR_USERNAME.github.io/bpdoctor-site/` within 2 minutes

### Step 3: Custom Domain (bpdoctor.dev)
1. Buy `bpdoctor.dev` from Namecheap, Cloudflare Registrar, or Google Domains (~$12/yr for .dev)
2. In the repo, create a file named `CNAME` containing one line:
   ```
   bpdoctor.dev
   ```
3. At your domain registrar, add these DNS records:
   ```
   Type   Name   Value
   A      @      185.199.108.153
   A      @      185.199.109.153
   A      @      185.199.110.153
   A      @      185.199.111.153
   CNAME  www    YOUR_USERNAME.github.io.
   ```
4. Back in GitHub Pages settings, enter `bpdoctor.dev` in the Custom Domain field
5. Check **Enforce HTTPS** (automatic SSL via Let's Encrypt — required for .dev domains)
6. Wait 15-30 minutes for DNS propagation and certificate issuance

---

## Before-Launch Checklist

### Assets to Create (put in `assets/` folder)
- [ ] `demo.gif` — Screen recording of BP Doctor scanning a project (800x500px, <5MB, 10-15 seconds)
      Record with: ShareX (free), ScreenToGif, or OBS -> ffmpeg gif conversion
      Content: Open GUI -> select project -> scan runs -> results appear -> auto-fix one issue
- [ ] `og-card.png` — Social sharing image (1200x630px)
      Content: BP Doctor logo + tagline + dark background + scan result screenshot
- [ ] `favicon.png` — 32x32 and 180x180 versions of the logo icon

### Replace Demo GIF
In `index.html`, find the `.demo-placeholder` div and replace it with:
```html
<img src="assets/demo.gif" alt="BP Doctor scanning a UE5 project" loading="lazy">
```

### Services to Set Up

#### Google Analytics
1. Go to analytics.google.com -> Create property -> Web
2. Get your Measurement ID (G-XXXXXXXXXX)
3. Replace `G-XXXXXXXXXX` in the two script tags at the bottom of index.html

#### Email Capture (Formspree — free tier: 50 submissions/month)
1. Go to formspree.io -> Create account -> New Form
2. Get your form endpoint (looks like: `https://formspree.io/f/xabcdefg`)
3. Replace `YOUR_FORM_ID` in the exit-intent popup form action
4. Alternative: use Buttondown (free <100 subscribers) for a proper newsletter

#### Store Links
Replace placeholder URLs with your actual store pages:
- Gumroad: `https://YOUR_ACCOUNT.gumroad.com/l/bpdoctor-standard`
- Gumroad Pro: `https://YOUR_ACCOUNT.gumroad.com/l/bpdoctor-pro`
- Fab.com: Your Fab listing URL once approved
- Itch.io: Your itch.io page URL

### Testimonials
The three testimonial cards currently describe internal testing scenarios. Replace them with
real user quotes as reviews come in. Update the Schema.org `aggregateRating` to match.

---

## UTM Links for Marketing

Use these when sharing:
```
# Reddit
https://bpdoctor.dev?utm_source=reddit&utm_medium=social&utm_campaign=launch

# Twitter/X
https://bpdoctor.dev?utm_source=twitter&utm_medium=social&utm_campaign=launch

# UE Forums
https://bpdoctor.dev?utm_source=ue_forums&utm_medium=forum&utm_campaign=launch

# Discord
https://bpdoctor.dev?utm_source=discord&utm_medium=social&utm_campaign=launch

# YouTube video description
https://bpdoctor.dev?utm_source=youtube&utm_medium=video&utm_campaign=launch
```

The landing page JavaScript automatically captures UTM params and appends them to
Gumroad purchase links, so you can track which channel drives conversions.

---

## Performance Notes

- Single HTML file: ~35KB uncompressed, ~10KB gzipped (GitHub Pages gzips automatically)
- Google Fonts loaded async with `display=swap` — no render blocking
- No JavaScript frameworks — vanilla JS, ~2KB
- All animations are CSS-only (no JS animation libraries)
- Images are the only external assets to optimize

## Target: 5%+ Conversion Rate

Conversion levers built into this page:
1. **Problem-first headline** — visitors self-identify within 2 seconds
2. **Proof bar** — 5 trust signals visible without scrolling
3. **Animated demo** — scanning animation runs automatically (replace with real GIF)
4. **Sticky header CTA** — always one click away from pricing
5. **Exit-intent popup** — captures emails from bouncing visitors
6. **Price anchoring** — Enterprise at $399 makes Pro at $14.99 feel trivial
7. **FAQ objection handling** — answers the 7 most common purchase blockers
8. **Two CTA buttons** — above the fold AND after the full pitch
9. **UTM tracking** — know exactly which channels convert
