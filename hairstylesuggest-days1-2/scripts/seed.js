#!/usr/bin/env node
/**
 * Seed Script — creates the 10 initial hairstyles via the Strapi REST API.
 *
 * Usage:
 *   STRAPI_URL=http://localhost:1337 JWT_TOKEN=your_admin_jwt node scripts/seed.js
 *
 * How to get your JWT_TOKEN:
 *   1. Start Strapi (npm run develop inside /backend)
 *   2. Open http://localhost:1337/admin and create your admin account
 *   3. In a REST client (Bruno / Postman / curl), POST to:
 *        http://localhost:1337/api/auth/local
 *        Body: { "identifier": "your@email.com", "password": "yourpassword" }
 *   4. Copy the "jwt" field from the response into JWT_TOKEN
 *
 * The script is idempotent — it checks for existing slugs before creating.
 */

const STRAPI_URL = process.env.STRAPI_URL || 'http://localhost:1337';
const JWT_TOKEN  = process.env.JWT_TOKEN  || '';

if (!JWT_TOKEN) {
  console.error('❌  JWT_TOKEN is not set. See usage instructions at the top of this file.');
  process.exit(1);
}

// ── Catalog data — 10 initial hairstyles from Part 8 of the master plan ───────
const HAIRSTYLES = [
  {
    slug:            'low-fade-lineup',
    display_name:    'Low Fade + Lineup',
    category:        'fade',
    lora_checkpoint: null,
    lora_weight:     0.85,
    base_prompt:     'low skin fade on the sides and back, sharp lineup at the hairline, clean edges, well-defined temple fade, neat professional look',
    negative_prompt: 'uneven fade, rough edges, patchy hair, overgrown sides, messy hairline',
    is_premium:      false,
    sort_order:      1,
    active:          true,
    source_type:     'catalog',
  },
  {
    slug:            'mid-fade-clean',
    display_name:    'Mid Fade Clean Cut',
    category:        'fade',
    lora_checkpoint: null,
    lora_weight:     0.85,
    base_prompt:     'mid skin fade, smooth gradient from skin to hair, clean cut top, well-blended sides, sharp neckline, modern barbershop finish',
    negative_prompt: 'uneven fade, patchy blend, rough neckline',
    is_premium:      false,
    sort_order:      2,
    active:          true,
    source_type:     'catalog',
  },
  {
    slug:            'high-top-fade',
    display_name:    'High Top Fade',
    category:        'fade',
    lora_checkpoint: null,
    lora_weight:     0.85,
    base_prompt:     'high top fade hairstyle, flat top squared at the crown, tight fade on the sides, tall box shape on top, defined edges, 90s inspired modern revival',
    negative_prompt: 'uneven top, slanted flat top, patchy sides',
    is_premium:      false,
    sort_order:      3,
    active:          true,
    source_type:     'catalog',
  },
  {
    slug:            'box-braids-medium',
    display_name:    'Medium Box Braids',
    category:        'braids',
    lora_checkpoint: null,
    lora_weight:     0.85,
    base_prompt:     'medium length box braids, neatly sectioned and parted, uniform braid size, smooth braid texture, dark brown color, clean scalp-level partings',
    negative_prompt: 'tangled braids, uneven braid size, frizzy braids, messy partings',
    is_premium:      false,
    sort_order:      4,
    active:          true,
    source_type:     'catalog',
  },
  {
    slug:            'cornrows-straight-back',
    display_name:    'Straight Back Cornrows',
    category:        'braids',
    lora_checkpoint: null,
    lora_weight:     0.85,
    base_prompt:     'straight back cornrows, neat rows braided flat against the scalp, uniform width rows, clean center part, tight scalp braids going from hairline to back',
    negative_prompt: 'uneven rows, loose cornrows, bumpy rows, crooked rows',
    is_premium:      false,
    sort_order:      5,
    active:          true,
    source_type:     'catalog',
  },
  {
    slug:            'short-locs-starter',
    display_name:    'Starter Locs',
    category:        'locs',
    lora_checkpoint: null,
    lora_weight:     0.85,
    base_prompt:     'starter dreadlocks, short early-stage locs, neat cylindrical loc shape, well-parted sections, fresh retwist appearance, uniform loc size',
    negative_prompt: 'frizzy locs, tangled locs, unformed locs, messy roots',
    is_premium:      true,
    sort_order:      6,
    active:          true,
    source_type:     'catalog',
  },
  {
    slug:            'medium-locs-neat',
    display_name:    'Medium Dreadlocks',
    category:        'locs',
    lora_checkpoint: null,
    lora_weight:     0.85,
    base_prompt:     'medium length mature dreadlocks, well-formed cylindrical locs, neat and tidy appearance, consistent loc thickness, natural dark brown color, healthy loc texture',
    negative_prompt: 'tangled locs, thin locs, uneven locs, frizzy ends',
    is_premium:      true,
    sort_order:      7,
    active:          true,
    source_type:     'catalog',
  },
  {
    slug:            'afro-medium-shaped',
    display_name:    'Shaped Medium Afro',
    category:        'afro',
    lora_checkpoint: null,
    lora_weight:     0.85,
    base_prompt:     'medium shaped afro hairstyle, perfectly rounded shape, full and voluminous, evenly picked out afro, natural coily texture, symmetrical round silhouette',
    negative_prompt: 'flat afro, matted afro, uneven shape, lopsided afro',
    is_premium:      false,
    sort_order:      8,
    active:          true,
    source_type:     'catalog',
  },
  {
    slug:            'bald-fade-beard',
    display_name:    'Bald Fade + Beard',
    category:        'fade',
    lora_checkpoint: null,
    lora_weight:     0.85,
    base_prompt:     'bald skin fade on the sides, seamlessly blending into a full neatly trimmed beard, sharp beard line, well-groomed beard, clean shaved top, connected beard to fade',
    negative_prompt: 'patchy beard, uneven fade, rough beard line, disconnected beard',
    is_premium:      true,
    sort_order:      9,
    active:          true,
    source_type:     'catalog',
  },
  {
    slug:            'twists-short',
    display_name:    'Short Two-Strand Twists',
    category:        'protective',
    lora_checkpoint: null,
    lora_weight:     0.85,
    base_prompt:     'short two-strand twists, neatly twisted sections, uniform twist size, well-defined twist pattern, natural hair texture visible, clean scalp partings',
    negative_prompt: 'unraveling twists, loose twists, uneven twist size, messy twists',
    is_premium:      true,
    sort_order:      10,
    active:          true,
    source_type:     'catalog',
  },
];

// ── Helpers ───────────────────────────────────────────────────────────────────

async function apiRequest(method, path, body = null) {
  const url  = `${STRAPI_URL}/api${path}`;
  const opts = {
    method,
    headers: {
      'Content-Type':  'application/json',
      'Authorization': `Bearer ${JWT_TOKEN}`,
    },
  };
  if (body) opts.body = JSON.stringify(body);

  const res = await fetch(url, opts);
  const json = await res.json();

  if (!res.ok) {
    const detail = json?.error?.message || JSON.stringify(json).slice(0, 200);
    throw new Error(`HTTP ${res.status} on ${method} ${path}: ${detail}`);
  }

  return json;
}

async function slugExists(slug) {
  try {
    const res = await apiRequest('GET', `/hairstyles/${slug}`);
    return !!res?.data;
  } catch {
    return false;
  }
}

// ── Main ──────────────────────────────────────────────────────────────────────

async function main() {
  console.log(`\n🌱  HairstyleSuggest Seed Script`);
  console.log(`📡  Strapi URL : ${STRAPI_URL}`);
  console.log(`📦  Hairstyles : ${HAIRSTYLES.length}\n`);

  let created = 0;
  let skipped = 0;
  let failed  = 0;

  for (const hs of HAIRSTYLES) {
    try {
      const exists = await slugExists(hs.slug);

      if (exists) {
        console.log(`  ⏩  Skipped  (already exists): ${hs.slug}`);
        skipped++;
        continue;
      }

      await apiRequest('POST', '/hairstyles', { data: hs });
      console.log(`  ✅  Created : ${hs.slug} — "${hs.display_name}"`);
      created++;

      // Small delay to avoid rate limits
      await new Promise(r => setTimeout(r, 150));

    } catch (err) {
      console.error(`  ❌  Failed  : ${hs.slug} — ${err.message}`);
      failed++;
    }
  }

  console.log('\n─────────────────────────────────');
  console.log(`✅  Created : ${created}`);
  console.log(`⏩  Skipped : ${skipped}`);
  console.log(`❌  Failed  : ${failed}`);
  console.log('─────────────────────────────────\n');

  if (failed > 0) process.exit(1);
}

main().catch(err => {
  console.error('Fatal:', err.message);
  process.exit(1);
});
