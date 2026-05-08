/* hr_manager_renderer.js
 * ==========================================================================
 * Extends hr_manager.html to render non-image artifacts (audio, HTML, JSON,
 * text) inline, using the new /asset-raw route. Works as a DOM observer so
 * it is compatible with the existing manager without modifying its render
 * functions.
 *
 * ACTIVATION
 * ----------
 * Inject before </body> in hr_manager.html:
 *     <script src="/ext/hr_manager_renderer.js"></script>
 *
 * HOW IT WORKS
 * ------------
 * The manager renders artifacts as <img> tags whose src points at
 * /image-raw?path=<file>. That breaks for audio, HTML, JSON, etc.
 *
 * This script:
 *   1. On each <img> that appears in the DOM, inspect the decoded path.
 *   2. If the path's extension maps to a non-image media type, REPLACE the
 *      <img> with a type-appropriate widget that fetches from /asset-raw.
 *   3. If the path is an image, do nothing (fall through to native render).
 *
 * Safe to load more than once -- guarded by a window-level flag.
 * ==========================================================================
 */

(function () {
    'use strict';
    if (window.__mv_renderer_loaded) return;
    window.__mv_renderer_loaded = true;

    const AUDIO_EXT = new Set(['mp3', 'wav', 'flac', 'm4a', 'ogg']);
    const VIDEO_EXT = new Set(['mp4', 'mov', 'avi', 'mkv', 'webm']);
    const IMAGE_EXT = new Set(['jpg', 'jpeg', 'png', 'gif', 'webp',
                               'heic', 'heif', 'bmp', 'tiff', 'tif']);
    const HTML_EXT  = new Set(['html', 'htm']);
    const TEXT_EXT  = new Set(['json', 'txt', 'md', 'log', 'csv', 'xml']);
    const PDF_EXT   = new Set(['pdf']);

    /** Extract the ?path= value from any /image-raw or /asset-raw URL.
     *  Returns null if the src isn't one of those routes. */
    function decodeAssetPath(src) {
        if (!src) return null;
        const m = src.match(/\/(image-raw|asset-raw)\?path=([^&]+)/);
        if (!m) return null;
        try { return decodeURIComponent(m[2]); } catch (e) { return null; }
    }

    function extOf(path) {
        const m = /\.([^.\\\/]+)$/.exec(path);
        return m ? m[1].toLowerCase() : '';
    }

    function fileName(path) {
        const m = /[\\\/]([^\\\/]+)$/.exec(path);
        return m ? m[1] : path;
    }

    function assetUrl(path) {
        return '/asset-raw?path=' + encodeURIComponent(path);
    }

    /** Build the correct widget for the file at `path`.
     *  Returns an HTMLElement ready to be inserted. */
    function buildWidget(path, fallbackImg) {
        const ext = extOf(path);
        const wrap = document.createElement('div');
        wrap.className = 'mv-ext-widget';
        wrap.dataset.mvPath = path;
        wrap.style.cssText = 'display:flex;flex-direction:column;gap:6px;' +
                             'padding:8px;background:var(--bg2,#222);' +
                             'border-radius:4px;max-width:100%;color:inherit';

        const title = document.createElement('div');
        title.textContent = fileName(path);
        title.style.cssText = 'font-size:12px;opacity:0.8;word-break:break-all';
        wrap.appendChild(title);

        if (AUDIO_EXT.has(ext)) {
            const a = document.createElement('audio');
            a.controls = true;
            a.preload = 'metadata';
            a.src = assetUrl(path);
            a.style.cssText = 'width:100%;max-width:500px';
            wrap.appendChild(a);
        } else if (VIDEO_EXT.has(ext)) {
            const v = document.createElement('video');
            v.controls = true;
            v.preload = 'metadata';
            v.src = assetUrl(path);
            v.style.cssText = 'width:100%;max-width:500px;max-height:400px';
            wrap.appendChild(v);
        } else if (HTML_EXT.has(ext)) {
            const f = document.createElement('iframe');
            f.src = assetUrl(path);
            f.style.cssText = 'width:100%;height:400px;border:1px solid var(--bg3,#333);' +
                              'border-radius:4px;background:#fff';
            f.setAttribute('sandbox', 'allow-same-origin');  // block scripts in archived pages
            wrap.appendChild(f);
            const open = document.createElement('a');
            open.href = assetUrl(path);
            open.target = '_blank';
            open.rel = 'noopener';
            open.textContent = 'open in new tab';
            open.style.cssText = 'font-size:11px;color:var(--link,#6af)';
            wrap.appendChild(open);
        } else if (PDF_EXT.has(ext)) {
            const f = document.createElement('iframe');
            f.src = assetUrl(path);
            f.style.cssText = 'width:100%;height:500px;border:1px solid var(--bg3,#333);' +
                              'border-radius:4px';
            wrap.appendChild(f);
        } else if (TEXT_EXT.has(ext)) {
            const pre = document.createElement('pre');
            pre.style.cssText = 'max-height:400px;overflow:auto;padding:8px;' +
                                'background:var(--bg3,#111);border-radius:4px;' +
                                'font-size:12px;white-space:pre-wrap;word-break:break-all;' +
                                'color:inherit';
            pre.textContent = 'loading...';
            wrap.appendChild(pre);
            fetch(assetUrl(path))
                .then(r => r.text())
                .then(t => { pre.textContent = t.length > 50000
                    ? t.slice(0, 50000) + '\n\n... [truncated, ' + (t.length - 50000) + ' more chars]'
                    : t; })
                .catch(e => { pre.textContent = 'error: ' + e; });
        } else {
            // Unknown extension: show a download link and a hint
            const a = document.createElement('a');
            a.href = assetUrl(path);
            a.textContent = 'download ' + fileName(path);
            a.target = '_blank';
            a.rel = 'noopener';
            a.style.cssText = 'color:var(--link,#6af);text-decoration:underline';
            wrap.appendChild(a);
        }

        return wrap;
    }

    function upgradeImg(img) {
        if (img.dataset.mvUpgraded === '1') return;
        const path = decodeAssetPath(img.src);
        if (!path) return;
        const ext = extOf(path);
        if (IMAGE_EXT.has(ext) || !ext) return;  // let the image path render as-is
        img.dataset.mvUpgraded = '1';
        const widget = buildWidget(path, img);
        if (img.parentNode) {
            img.parentNode.replaceChild(widget, img);
        }
    }

    function scanAll(root) {
        (root || document).querySelectorAll('img').forEach(upgradeImg);
    }

    // Initial pass after the manager's own scripts have run
    function init() {
        scanAll(document);

        const observer = new MutationObserver(muts => {
            for (const m of muts) {
                for (const node of m.addedNodes) {
                    if (node.nodeType !== 1) continue;
                    if (node.tagName === 'IMG') {
                        upgradeImg(node);
                    } else if (node.querySelectorAll) {
                        node.querySelectorAll('img').forEach(upgradeImg);
                    }
                }
                if (m.type === 'attributes' && m.target.tagName === 'IMG') {
                    // manager reassigns src as selections change
                    m.target.dataset.mvUpgraded = '';
                    upgradeImg(m.target);
                }
            }
        });
        observer.observe(document.body, {
            childList: true,
            subtree: true,
            attributes: true,
            attributeFilter: ['src'],
        });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
