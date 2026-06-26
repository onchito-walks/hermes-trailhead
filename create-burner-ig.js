#!/usr/bin/env node
/**
 * create-burner-ig.js — Create Instagram burner account via stealth Chrome + guerrilla mail
 *
 * Usage:
 *   node create-burner-ig.js
 *
 * Output: Session cookies saved to ~/.hermes/state/instagram-cookies.json
 */

const puppeteer = require('puppeteer-extra');
const StealthPlugin = require('puppeteer-extra-plugin-stealth');
const https = require('https');
const fs = require('fs');
const path = require('path');

puppeteer.use(StealthPlugin());

const GUERRILLA_BASE = 'https://api.guerrillamail.com/ajax.php';
const COOKIES_FILE = path.join(process.env.HOME, '.hermes', 'state', 'instagram-cookies.json');

function guerrillaRequest(params) {
  return new Promise((resolve, reject) => {
    const qs = Object.entries(params).map(([k,v]) => `${k}=${encodeURIComponent(v)}`).join('&');
    const url = `${GUERRILLA_BASE}?${qs}`;
    https.get(url, { headers: { 'User-Agent': 'Mozilla/5.0' } }, (res) => {
      let data = '';
      res.on('data', c => data += c);
      res.on('end', () => {
        try { resolve(JSON.parse(data)); } catch(e) { reject(e); }
      });
    }).on('error', reject);
  });
}

async function waitForEmail(sidToken, timeoutMs = 120000) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    const result = await guerrillaRequest({
      f: 'fetch_email',
      sid_token: sidToken,
    });
    if (result.list && result.list.length > 0) {
      return result.list[0];
    }
    await new Promise(r => setTimeout(r, 3000));
  }
  return null;
}

function extractCode(emailBody) {
  // Instagram sends a 6-digit code
  const match = emailBody.match(/\b(\d{6})\b/);
  return match ? match[1] : null;
}

async function main() {
  console.log('=== Creating Instagram Burner Account ===\n');

  // Step 1: Get temp email
  console.log('1. Getting temp email...');
  const emailResult = await guerrillaRequest({
    f: 'get_email_address',
    ip: '127.0.0.1',
    agent: 'Mozilla_5_0',
  });
  const email = emailResult.email_addr;
  const sidToken = emailResult.sid_token;
  console.log(`   Email: ${email}`);

  // Step 2: Launch stealth browser
  console.log('2. Launching stealth browser...');
  const browser = await puppeteer.launch({
    headless: 'new',
    args: ['--no-sandbox', '--disable-setuid-sandbox'],
  });
  const page = await browser.newPage();
  await page.setViewport({ width: 1280, height: 900 });
  await page.setUserAgent(
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36'
  );

  // Step 3: Navigate to Instagram signup
  console.log('3. Navigating to Instagram signup...');
  await page.goto('https://www.instagram.com/accounts/emailsignup/', {
    waitUntil: 'networkidle2',
    timeout: 30000,
  });
  await new Promise(r => setTimeout(r, 2000));

  // Step 4: Fill signup form (keyboard typing for React components)
  console.log('4. Filling signup form via keyboard typing...');
  
  const username = `trailhead_research_${Date.now().toString(36)}`;
  const accountPassword = 'Tr4!lh34dR3s34rch!!99';
  
  // Get all inputs
  const inputTypes = await page.evaluate(() => {
    return Array.from(document.querySelectorAll('input:not([type="hidden"])')).map(i => ({
      type: i.type,
      placeholder: i.placeholder || '',
      aria: i.getAttribute('aria-label') || '',
    }));
  });
  console.log(`   Inputs: ${JSON.stringify(inputTypes)}`);
  
  // Get all inputs as element handles
  const allInputEls = await page.$$('input:not([type="hidden"])');
  const pwEls = await page.$$('input[type="password"]');
  const searchEls = await page.$$('input[type="search"]');
  const selectEls = await page.$$('select');
  const textEls = [];
  for (const el of allInputEls) {
    const t = await el.evaluate(e => e.type);
    if (t === 'text') textEls.push(el);
  }
  
  // Fill email — click + select all + type
  if (textEls.length > 0) {
    await textEls[0].click();
    await page.keyboard.down('Control');
    await page.keyboard.press('a');
    await page.keyboard.up('Control');
    await page.keyboard.type(email, {delay: 10});
  }
  
  // Fill password
  if (pwEls.length > 0) {
    await pwEls[0].click();
    await page.keyboard.type(accountPassword, {delay: 10});
  }
  
  // Fill birthday selects
  if (selectEls.length >= 3) {
    await selectEls[0].select('6');
    await selectEls[1].select('15');
    await selectEls[2].select('1995');
    console.log('   Filled birthday');
  }
  
  // Fill name — click + select all + type
  if (textEls.length > 1) {
    await textEls[1].click();
    await page.keyboard.down('Control');
    await page.keyboard.press('a');
    await page.keyboard.up('Control');
    await page.keyboard.type('Trailhead Research', {delay: 10});
  }
  
  // Fill username
  if (searchEls.length > 0) {
    await searchEls[0].click();
    await page.keyboard.down('Control');
    await page.keyboard.press('a');
    await page.keyboard.up('Control');
    await page.keyboard.type(username, {delay: 10});
  }

  console.log(`   Username: ${username}`);

  // Step 5: Submit the form
  console.log('5. Submitting form...');
  
  // Take screenshot before submit for debugging
  await page.screenshot({ path: '/tmp/ig-before-submit.png' });
  
  // Try to click the submit/next button
  const clicked = await page.evaluate(() => {
    const buttons = document.querySelectorAll('button, div[role="button"], span[role="button"]');
    for (const b of buttons) {
      const text = (b.textContent || '').toLowerCase();
      if (text.includes('submit') || text.includes('next') || text.includes('sign up') || text.includes('continue')) {
        b.click();
        return 'clicked: ' + text.slice(0, 30);
      }
    }
    return 'no button found';
  });
  console.log(`   Submit: ${clicked}`);
  
  // Wait for navigation/redirect
  await new Promise(r => setTimeout(r, 8000));
  
  // Take screenshot after submit
  await page.screenshot({ path: '/tmp/ig-after-submit.png' });
  
  const currentUrl = page.url();
  const pageText = await page.evaluate(() => document.body.textContent.slice(0, 1000));
  console.log(`   URL: ${currentUrl}`);
  console.log(`   Page text sample: ${pageText.slice(0, 200)}`);
  
  // Check if we need verification
  if (pageText.includes('confirmation code') || pageText.includes('verification') || pageText.includes('checkpoint')) {
    console.log('   Verification required — saving screenshot, cannot auto-solve.');
    await browser.close();
    process.exit(2);
  }
  
  // Step 6: Export cookies
  console.log('6. Exporting cookies...');
  const cookies = await page.cookies();
  
  fs.mkdirSync(path.dirname(COOKIES_FILE), { recursive: true });
  fs.writeFileSync(COOKIES_FILE, JSON.stringify(cookies, null, 2));
  console.log(`   Saved ${cookies.length} cookies to ${COOKIES_FILE}`);

  // Verify login state
  const loggedIn = !pageText.includes('Log in') && !pageText.includes('Sign up');
  console.log(`   Logged in: ${loggedIn} (cookies: ${cookies.length})`);

  await browser.close();
  console.log('\n=== DONE ===');
}

main().catch(e => {
  console.error('FATAL:', e.message);
  process.exit(1);
});
