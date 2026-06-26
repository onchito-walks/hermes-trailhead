#!/usr/bin/env node
/**
 * stealth-extract.js — stealth-patched page text extraction
 *
 * Usage:
 *   node stealth-extract.js <url> [--cookies <path>] [--timeout <ms>] [--transcript]
 *
 * Uses puppeteer-extra + puppeteer-extra-plugin-stealth to bypass
 * bot detection on YouTube, TikTok, Instagram, and similar platforms.
 *
 * Output: JSON on stdout {ok, url, title, text, textLength, transcript, error}
 */

const puppeteer = require('puppeteer-extra');
const StealthPlugin = require('puppeteer-extra-plugin-stealth');

puppeteer.use(StealthPlugin());

function parseArgs() {
  const args = process.argv.slice(2);
  const opts = { url: null, cookies: null, timeout: 30000, transcript: false };
  for (let i = 0; i < args.length; i++) {
    if (args[i] === '--cookies' && i + 1 < args.length) {
      opts.cookies = args[++i];
    } else if (args[i] === '--timeout' && i + 1 < args.length) {
      opts.timeout = parseInt(args[++i], 10);
    } else if (args[i] === '--transcript') {
      opts.transcript = true;
    } else if (!opts.url) {
      opts.url = args[i];
    }
  }
  return opts;
}

async function extractYouTubeTranscript(page) {
  try {
    // YouTube transcript extraction via JS clicks (Puppeteer clicks blocked by anti-bot)
    await page.evaluate(() => {
      const moreBtn = document.querySelector('button[aria-label="More actions"]');
      if (moreBtn) moreBtn.click();
    });
    await new Promise(r => setTimeout(r, 1500));
    
    await page.evaluate(() => {
      const items = document.querySelectorAll('ytd-menu-service-item-renderer, tp-yt-paper-item');
      for (const el of items) {
        if (el.textContent.toLowerCase().includes('transcript')) {
          el.click();
          return;
        }
      }
      // Fallback: direct button selector
      const btn = document.querySelector('button[aria-label*="transcript"], button[aria-label*="Transcript"]');
      if (btn) btn.click();
    });
    await new Promise(r => setTimeout(r, 4000));
    
    // Extract transcript text from the panel
    const transcript = await page.evaluate(() => {
      const segs = document.querySelectorAll('ytd-transcript-segment-renderer');
      if (segs.length > 0) {
        return Array.from(segs).map(s => s.textContent.trim()).join('\n');
      }
      // Try broader panel extraction
      const panel = document.querySelector('#panels');
      if (panel) {
        const transcriptText = panel.querySelector('[slot="content"]') || panel.querySelector('yt-formatted-string');
        if (transcriptText) return transcriptText.textContent.trim();
        // Last resort: panel text minus headers
        const text = panel.textContent || '';
        // Filter out UI labels, keep only actual transcript lines
        const lines = text.split('\n').filter(l => {
          const t = l.trim();
          return t.length > 10 && !t.includes('Transcript') && !t.includes('Chapters') && !t.includes('Comments');
        });
        return lines.join('\n');
      }
      return null;
    });
    
    return transcript;
  } catch (e) {
    return null;
  }
}

async function main() {
  const opts = parseArgs();
  if (!opts.url) {
    console.log(JSON.stringify({ ok: false, error: 'No URL provided' }));
    process.exit(1);
  }

  let browser;
  try {
    browser = await puppeteer.launch({
      headless: 'new',
      args: [
        '--no-sandbox',
        '--disable-setuid-sandbox',
        '--disable-blink-features=AutomationControlled',
        '--disable-features=IsolateOrigins,site-per-process',
        '--disable-site-isolation-trials',
      ],
      timeout: opts.timeout,
    });

    const page = await browser.newPage();

    // Set a realistic viewport
    await page.setViewport({ width: 1280, height: 720 });

    // Set a realistic user agent
    await page.setUserAgent(
      'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36'
    );

    // Load cookies if provided
    if (opts.cookies) {
      const fs = require('fs');
      try {
        const cookieData = JSON.parse(fs.readFileSync(opts.cookies, 'utf8'));
        await page.setCookie(...cookieData);
      } catch (e) {
        // cookies file not found or invalid — continue without
      }
    }

    // Navigate with longer timeout for slow sites
    await page.goto(opts.url, {
      waitUntil: 'domcontentloaded',
      timeout: opts.timeout,
    });

    // Wait a bit for dynamic content
    await new Promise(r => setTimeout(r, 3000));

    // Get page title
    const title = await page.title();

    // Get visible text
    const text = await page.evaluate(() => {
      // Remove script/style content
      const clone = document.body.cloneNode(true);
      clone.querySelectorAll('script, style, noscript, [aria-hidden="true"]').forEach(el => el.remove());
      return clone.textContent.replace(/\s+/g, ' ').trim();
    });

    // Try transcript extraction for YouTube
    let transcript = null;
    if (opts.transcript && opts.url.includes('youtube.com')) {
      transcript = await extractYouTubeTranscript(page);
    }

    await browser.close();

    console.log(JSON.stringify({
      ok: true,
      url: opts.url,
      title: title || '',
      text: text || '',
      textLength: text ? text.length : 0,
      transcript: transcript,
    }));
    process.exit(0);

  } catch (e) {
    if (browser) {
      try { await browser.close(); } catch {}
    }
    console.log(JSON.stringify({
      ok: false,
      url: opts.url,
      error: e.message || String(e),
    }));
    process.exit(1);
  }
}

main();
