/*
 * animation.js — rendering engine for the communication animations.
 * Mounts nothing on its own: load animations.css, then call mountCard().
 * Texts are English by default. Override them with PymissiveAnimation.setLabels({...}), or
 * with a <script type="application/json" id="pymissive-animation-labels"> block in the page
 * (the {% pymissive_animations_labels %} template tag writes one, translated).
 */
(function (global) {
  'use strict';

  const DEFAULT_LABELS = {
    'email.title': 'Email',
    'email.subtitle': 'An email arrives in an inbox',
    'emailAR.title': 'Email with AR',
    'emailAR.subtitle': 'Read or delivery confirmation',
    'postal.title': 'Postal mail',
    'postal.subtitle': 'Envelopes arrive in the mailbox',
    'registered.title': 'Registered mail with AR',
    'registered.subtitle': 'Tracked envelope and proof of delivery',
    'handDelivery.title': 'Hand delivery',
    'handDelivery.subtitle': 'The letter is handed over against signature',
    'sms.title': 'SMS',
    'sms.subtitle': 'Messages arrive on the phone',
    'voice.title': 'Voice call',
    'voice.subtitle': 'A call arrives on the phone',
    'notification.title': 'Notification',
    'notification.subtitle': 'A notification arrives on the phone',
    'receiver.email': 'Screen — Email',
    'receiver.emailAR': 'Screen — Email with AR',
    'receiver.mailbox': 'Mailbox',
    'receiver.mailboxAR': 'Mailbox with AR',
    'receiver.doorstep': 'Door — Hand delivery',
    'receiver.sms': 'Phone — SMS',
    'receiver.voice': 'Phone — Voice call',
    'receiver.notification': 'Phone — Notification',
    'receiver.globe': 'Globe',
    'scene.arMark': 'AR',
    'scene.receiptTitle': 'Email received',
    'scene.receiptText': 'Confirmation sent',
    'scene.smsSample': 'Hi! 👋',
    'scene.smsApp': 'Messages',
    'scene.smsReceived': 'Hello!',
    'scene.smsSent': 'How are you?',
    'scene.incomingCall': 'Incoming call',
    'scene.voiceMessage': 'Voice',
    'scene.noticeTitle': 'Notification',
    'scene.noticeText': 'New message',
    'scene.receiptStamp': 'RECEIPT ACKNOWLEDGED',
    'scene.handedStamp': 'HANDED OVER',
    'combination.subtitle': 'Custom combination',
    'combination.aria': 'Preview of the send to the selected receiver',
    'counter.aria': 'Send progress counter',
    'counter.progressAria': 'Send progress',
    'counter.remaining': 'remaining',
    'counter.processed': 'processed',
    'counter.sentOne': 'sent',
    'counter.sentMany': 'sent',
    'counter.errorOne': 'error',
    'counter.errorMany': 'errors',
    'counter.summaryTitle': '{sent} sent, {errors} errors out of {total}',
    'counter.totalTitle': '{total} sends in total',
    'end.sent': 'Sent',
    'end.cancelled': 'Cancelled'
  };

  // One entry per send type. The animation cycle lives in the CSS variable, read at mount time;
  // receiver is the one used when a single type is mounted without options.receiver.
  const PRESETS = {
    email: { icon: '📧', selector: '.email-fly', cycleVar: '--email-cycle', receiver: 'email' },
    emailAR: { icon: '📩', selector: '.email-fly', cycleVar: '--email-cycle', receiver: 'emailAR' },
    postal: { icon: '📬', selector: '.fly', cycleVar: '--postal-cycle', receiver: 'mailbox' },
    registered: { icon: '✍', selector: '.registered', cycleVar: '--postal-cycle', receiver: 'mailboxAR' },
    handDelivery: { icon: '🤝', selector: '.handed', cycleVar: '--postal-cycle', receiver: 'doorstep' },
    sms: { icon: '💬', selector: '.sms-message', cycleVar: '--sms-cycle', receiver: 'sms' },
    voice: { icon: '☎', selector: '.call-signal', cycleVar: '--sms-cycle', receiver: 'voice' },
    notification: { icon: '🔔', selector: '.notice', cycleVar: '--sms-cycle', receiver: 'notification' }
  };
  // Simplified coastlines as flat [lon, lat, lon, lat, ...] lists.
  const GLOBE_LAND = [
    [-168,66,-162,70,-156,71.3,-140,70,-128,70,-115,68,-95,72,-82,73,-80,63,-94,59,-92,57,-82,55,-79,52,-78,58,-72,61,-64,60,-61,56,-56,52,-60,47,-66,44,-70,42,-74,40,-76,35,-81,31,-80,25,-82,27,-83,29,-85,30,-90,29,-94,29.5,-97,27,-97,22,-95,18.5,-91,19,-87,21,-88,16,-84,15,-83,10,-79.5,9,-77.5,8,-80,7.5,-83,8.5,-86,12,-88,13.5,-92,14.5,-95,16,-100,17,-105,20,-106,23,-109,25,-112,29,-114.8,31.8,-113,29,-110,24,-109.5,23,-112,25,-114,27.5,-116,30,-117,32.5,-121,35,-124,40,-124,46,-123,49,-128,51,-133,56,-140,60,-147,61,-152,59,-158,57,-164,55,-158,58,-162,59,-165,62,-165,64.5],
    [-85,22,-82,23.2,-77,22,-74.2,20.1,-77.5,19.9,-81,21.6],
    [-74.4,19.8,-70,19.8,-68.4,18.5,-71.5,17.6,-74.4,18.4],
    [-77,8.5,-72,12,-64,10.5,-60,8.5,-52,5,-50,0,-44,-2.5,-35,-5,-35,-9,-39,-13.5,-39,-18,-41,-22,-48,-26,-48.5,-28.5,-53,-34,-57,-35,-57.5,-38,-62,-39,-65,-42,-64,-45,-67.5,-46.5,-66,-48.5,-69,-51,-68.5,-52.5,-70,-54.5,-74,-53,-75,-48,-73.5,-42,-73,-37,-71.5,-30,-70.3,-18,-75,-15,-77,-12,-81,-5,-80,-1,-78.5,2,-77.5,7],
    [-9,43,-9,39,-9,37,-6,36,-2,36.7,0,38.5,0.3,40,3.2,42,3.2,43.3,6,43,8.5,44.3,10.2,43.9,12.3,41.7,15.6,40,16,38,16.6,38.4,17,39,18.5,40.2,16,41.4,14,42.5,12.3,44.2,13.6,45.6,15,44,19,41.8,19.5,40,21,38,22.5,36.5,23,38,24,40,26,40.8,26,38,28,36.7,36,36.5,35,33,34.3,31.3,34.9,29.5,35,28,39,22,42.5,16,43.5,12.7,45,13,52,16,55,17.5,57.5,19,59.8,22.5,56.4,24.8,56,26.4,54,24.2,51.5,24.3,50.5,26,48.5,28.5,48,30,50,30,54,26.7,57,25.7,61.5,25.2,66.5,25.4,68,23.5,72.8,21,73,16,77.5,8,80.2,13,80.2,15.8,87,21.5,91.5,22.5,94,16,97.5,16.5,98.5,8,100.5,13.5,105,8.6,109,11.5,106.5,20.5,110,21.5,117,23,122,30,121,32,119,35,122.5,37,121,40.8,126,37.5,129.4,35.5,129.5,42.5,135,43.5,141,48.5,140.5,53,135,54.5,141,59,149,59.5,156,61.5,163,60,170,60,178,62.5,180,65,178,69,160,70,150,72,140,72.5,130,71,113,73.5,105,77.5,98,76,87,75,80,73,73,72,68,69,60,69,55,68,44,68.5,41,66.5,33,69.5,28,71,20,70,15,68.5,12.5,65,10.5,63.5,5,62,5,59,7,58,10.5,59.5,12,56,14,55.5,16,56.5,19,59.5,18,62.5,21,64.5,25,65.5,22.5,63,21.5,60.8,23,59.9,28,60.5,24,59.4,21.5,57.5,21,55,14,54,10.5,54.5,10,57.5,8,57,8.5,55,8.8,53.9,7,53.5,4.5,52.5,3,51.3,1.6,50.9,-1.5,49.6,-1.8,48.7,-4.6,48.4,-2,47,-1.2,46,-1.5,43.5,-8,43.7],
    [-5.7,50,1.4,51.2,1.7,52.7,0,53.5,-1.6,55.5,-2,57.6,-3.3,58.6,-5,58.6,-6.2,57.5,-5.5,55.5,-3,54.7,-3,53.4,-4.5,52.8,-5.2,51.7,-3.4,51.4],
    [-6,52.2,-6,54,-7.5,55.2,-10,54.2,-10,51.6],
    [-24,65.5,-22,66.4,-16,66.5,-13.6,65,-18.7,63.4,-22.7,63.8],
    [-17,21,-16,24,-13,27.6,-10,29.6,-9.6,32,-6.8,34,-5.9,35.8,-2,35.1,1,36.5,10,37.3,11,35.2,10,34,11,33.2,15.2,32.3,20,30.8,20,32.2,23,32.6,25,31.6,29,30.9,32.3,31.3,34.2,31.2,34.5,28,32.6,29.9,33.5,27.5,35.5,24,37.3,21,38.5,18,39.7,15.5,42.5,13,43.3,11.8,44.5,10.4,51.2,11.8,51,10.5,49.5,6.5,48,4.5,43,-1,40.2,-2.8,39.2,-4.6,39.3,-8,40.5,-10.5,40.5,-15,35.5,-21.5,35.5,-24,32.9,-26,32.4,-28.6,30,-31.3,27,-33.5,22.5,-34,20,-34.8,18.4,-34,18.2,-31.6,15.2,-27.1,14.4,-22.9,11.8,-17.3,13.6,-12,13,-8.5,12.3,-6,9.5,-2,9.6,2.5,9.5,3.9,8.5,4.5,6,4.3,4.4,6.3,1.9,6.2,-2,4.8,-4,5.2,-7.5,4.4,-9.3,5.6,-12.5,7.6,-13.3,9.3,-15,10.9,-16.7,12.4,-17.2,14.7,-16.5,16.2,-16.2,19],
    [49.3,-12,50.4,-15.5,49.5,-17,47.5,-24.8,45.2,-25.5,43.7,-23.5,44.3,-20.5,44.4,-16.5,46.4,-15.7,48,-13.7],
    [113.5,-22,114,-26.5,115,-34,118,-35,123,-34,129,-31.6,134,-32.5,138,-35,140,-38,144,-38.5,147,-38.5,150,-37.5,151,-34,153,-31,153.5,-28,153,-25,150.5,-22.5,149,-20.5,146,-18.5,145.5,-15,143.5,-14,142.5,-10.7,141.5,-13,141.6,-17,140,-17.7,137,-15.8,136,-12.5,132.5,-11.3,130,-12.3,129.5,-15,126,-14,122.5,-17,121,-19.5,117,-20.7,114,-21.8],
    [144.6,-40.7,148.3,-40.9,148,-43,146.8,-43.6,145.2,-42.2],
    [131,-1.5,134,-0.9,138,-1.6,141,-2.6,145.5,-4.5,147.5,-6.2,147.5,-8,150,-10.4,146,-8.8,143.5,-9,141,-9.1,138,-8.3,137.8,-5.3,135,-4.3,132.5,-4,131.8,-2.8],
    [109.3,1.9,111,1.5,113,3.2,116,6.9,117.7,5.8,119,5,118,2.3,117.9,0.8,116.5,-1.5,116,-3.8,114.5,-4,111.5,-3,110,-1.8,109,0],
    [95.3,5.6,97.5,5.2,100.4,2.2,104,-1,106,-3,105.8,-5.8,104.5,-5.9,102.3,-4,100.4,-1,98.7,1.7],
    [105.2,-6.8,108,-6.3,111,-6.4,114.5,-7.7,114.4,-8.7,110,-8.1,106,-7.4],
    [120.6,18.5,122.3,18.3,122,16,124,12.5,126,9,126.5,7,125.5,6,124,6.5,122,7,123,9.5,122,11.5,120.5,14.5,120,16],
    [130,31.3,131.5,31.4,132,33.8,135,33.5,137,34.6,139.8,35,141,37,142,39.5,141.4,41.4,140,40.5,139.5,38,136.8,37.3,135.8,35.5,133,35.6,131,34.4,129.6,33.2],
    [140,41.4,141.5,42.5,143.3,42,145.5,43.3,144.5,44.1,141.8,45.5,141.3,43.3,140,42.7],
    [172.7,-34.4,174.5,-36.5,176,-37.6,178.5,-37.7,177.9,-39.2,176.9,-39.6,174.9,-41.5,174.6,-39.8,173.8,-39.2,174.6,-37.5],
    [172.7,-40.5,174.3,-41.3,173.1,-43,171.2,-44.5,170.6,-45.9,168.4,-46.6,166.5,-46,167.2,-44.9,170.5,-43,172,-41.5],
    [79.9,9.8,81.9,7.5,81.3,6.2,80.1,6,79.7,8.2]
  ];
  const GLOBE_ICE = [[-73,78,-60,82,-30,83.5,-20,81,-18,76,-22,70,-32,68,-40,65,-43,60,-48,61,-52,65,-54,69,-58,75,-66,76]];
  const GLOBE_TILT = 12;
  const GLOBE_START = -25;
  const GLOBE_DEGREES_PER_SECOND = 12;
  const GLOBE_ICE_RGB = [244, 248, 251];
  const MASK_WIDTH = 720;
  const MASK_HEIGHT = 360;
  let globeMask = null;
  // Equirectangular map at half a degree per cell: 0 ocean, 1 land, 2 ice. Built once per page.
  function globeLandMask() {
    if (globeMask) return globeMask;
    const canvas = document.createElement('canvas');
    canvas.width = MASK_WIDTH;
    canvas.height = MASK_HEIGHT;
    const ctx = canvas.getContext('2d', { willReadFrequently: true });
    function fill(shapes, color) {
      ctx.fillStyle = color;
      shapes.forEach(points => {
        ctx.beginPath();
        for (let i = 0; i < points.length; i += 2) ctx.lineTo((points[i] + 180) * 2, (90 - points[i + 1]) * 2);
        ctx.fill();
      });
    }
    fill(GLOBE_LAND, '#f00');
    fill(GLOBE_ICE, '#00f');
    ctx.fillRect(0, 0, MASK_WIDTH, (90 - 72) * 2);
    ctx.fillRect(0, (90 + 62) * 2, MASK_WIDTH, MASK_HEIGHT);
    const data = ctx.getImageData(0, 0, MASK_WIDTH, MASK_HEIGHT).data;
    globeMask = new Uint8Array(MASK_WIDTH * MASK_HEIGHT);
    for (let i = 0; i < globeMask.length; i++) globeMask[i] = data[i * 4 + 2] > 127 ? 2 : data[i * 4] > 127 ? 1 : 0;
    return globeMask;
  }
  // The land colour comes from CSS (color-mix with the brand), so let the canvas parse it.
  function rgbOf(color) {
    const ctx = document.createElement('canvas').getContext('2d');
    ctx.fillStyle = '#8bd3a0';
    ctx.fillStyle = color;
    ctx.fillRect(0, 0, 1, 1);
    return ctx.getImageData(0, 0, 1, 1).data;
  }
  // Orthographic globe drawn pixel by pixel: each pixel's latitude and relative longitude are
  // computed once, so a frame only shifts the longitude and looks the mask up.
  function startGlobe(node, shell) {
    const canvas = node.querySelector('canvas');
    const size = Math.round((node.offsetWidth || 120) * Math.min(2, global.devicePixelRatio || 1));
    canvas.width = size;
    canvas.height = size;
    const ctx = canvas.getContext('2d');
    const image = ctx.createImageData(size, size);
    const mask = globeLandMask();
    const tilt = GLOBE_TILT * Math.PI / 180;
    const offsets = [];
    const rows = [];
    const longitudes = [];
    for (let py = 0; py < size; py++) {
      for (let px = 0; px < size; px++) {
        const x = (px + 0.5) / size * 2 - 1;
        const y = 1 - (py + 0.5) / size * 2;
        const r2 = x * x + y * y;
        if (r2 > 1) continue;
        const z = Math.sqrt(1 - r2);
        const lat = Math.asin(y * Math.cos(tilt) + z * Math.sin(tilt)) * 180 / Math.PI;
        offsets.push((py * size + px) * 4);
        rows.push(Math.min(MASK_HEIGHT - 1, Math.floor((90 - lat) * 2)) * MASK_WIDTH);
        longitudes.push(Math.atan2(x, z * Math.cos(tilt) - y * Math.sin(tilt)) * 180 / Math.PI);
      }
    }
    let centre = GLOBE_START;
    let landColor = '';
    let land = null;
    function draw() {
      const color = getComputedStyle(canvas).color;
      if (color !== landColor) {
        landColor = color;
        land = rgbOf(color);
      }
      const data = image.data;
      for (let i = 0; i < offsets.length; i++) {
        let column = Math.floor((longitudes[i] + centre + 180) * 2) % MASK_WIDTH;
        if (column < 0) column += MASK_WIDTH;
        const kind = mask[rows[i] + column];
        const rgb = kind === 2 ? GLOBE_ICE_RGB : land;
        const p = offsets[i];
        data[p] = rgb[0];
        data[p + 1] = rgb[1];
        data[p + 2] = rgb[2];
        data[p + 3] = kind ? 255 : 0;
      }
      ctx.putImageData(image, 0, 0);
    }
    draw();
    if (global.matchMedia && global.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
    let previous = 0;
    let frame = 0;
    function tick(time) {
      if (shell.destroyed) return;
      // About 30 frames per second is plenty for a slow spin.
      if (time - previous >= 33) {
        if (previous) centre -= GLOBE_DEGREES_PER_SECOND * Math.min(100, time - previous) / 1000;
        if (centre < -180) centre += 360;
        previous = time;
        draw();
      }
      frame = requestAnimationFrame(tick);
    }
    frame = requestAnimationFrame(tick);
    shell.cleanups.push(() => cancelAnimationFrame(frame));
  }

  const RECEIVERS = {
    email: { preset: 'email', selector: '.desktop', endX: 'calc(100% - 7% - 95px)', endY: '136.5px', scale: '.27' },
    emailAR: { preset: 'emailAR', selector: '.desktop', stageClass: 'ar-desktop', endX: 'calc(100% - 7% - 95px)', endY: '136.5px', scale: '.27' },
    mailbox: { preset: 'postal', selector: '.mailbox', endX: 'calc(100% - 10% - 66px)', endY: '130px', scale: '.3' },
    mailboxAR: { preset: 'registered', selector: '.mailbox', signature: '.signature-card', endX: 'calc(100% - 10% - 66px)', endY: '130px', scale: '.3' },
    doorstep: { preset: 'handDelivery', selector: '.doorstep', signature: '.signature-card', endX: 'calc(100% - 10% - 66px)', endY: '195px', scale: '.3' },
    sms: { preset: 'sms', selector: '.phone', endX: 'calc(100% - 12% - 56px)', endY: '143px', scale: '.15' },
    voice: { preset: 'voice', selector: '.phone', endX: 'calc(100% - 12% - 56px)', endY: '143px', scale: '.15' },
    notification: { preset: 'notification', selector: '.phone', endX: 'calc(100% - 12% - 56px)', endY: '143px', scale: '.15' },
    // Channel-neutral receiver, meant for mixed sender types.
    globe: {
      html: '<div class="globe"><canvas></canvas><div class="globe-shade"></div></div>',
      setup: startGlobe,
      endX: 'calc(100% - 10% - 66px)', endY: '115px', scale: '.25'
    }
  };

  const labels = Object.assign({}, DEFAULT_LABELS);
  let pageLabelsRead = false;
  function readPageLabels() {
    if (pageLabelsRead) return;
    pageLabelsRead = true;
    const node = document.getElementById('pymissive-animation-labels');
    if (!node) return;
    try {
      Object.assign(labels, JSON.parse(node.textContent));
    } catch (error) {
      console.warn('PymissiveAnimation: invalid labels JSON', error);
    }
  }
  function t(key, params) {
    readPageLabels();
    let text = String(labels[key] ?? DEFAULT_LABELS[key] ?? key);
    if (params) Object.keys(params).forEach(name => { text = text.split('{' + name + '}').join(params[name]); });
    return text;
  }
  function setLabels(overrides) {
    readPageLabels();
    Object.assign(labels, overrides || {});
    Object.keys(sourceCache).forEach(key => { delete sourceCache[key]; });
  }
  function escapeHtml(text) {
    return String(text).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }
  function locale() {
    return document.documentElement.lang || undefined;
  }
  function formatNumber(value) {
    return value.toLocaleString(locale());
  }
  function formatPercent(value) {
    return new Intl.NumberFormat(locale(), {
      style: 'percent', minimumFractionDigits: 1, maximumFractionDigits: 1
    }).format(value / 100);
  }

  const CLOUDS = '<div class="cloud l"></div><div class="cloud r"></div><div class="ground"></div>';
  function item(className, inner = '', attributes = '') {
    return `<div class="${className}"${attributes}>${inner}</div>`;
  }
  function desktop(overlay) {
    return '<div class="desktop"><div class="monitor"><div class="screen"><div class="mail-app-top"></div>'
      + '<div class="inbox-side"></div><div class="email-list"></div><div class="email-list two"></div>'
      + `<div class="email-list three"></div>${overlay}</div></div><div class="monitor-neck"></div>`
      + '<div class="monitor-base"></div></div>';
  }
  const MAILBOX = '<div class="mailbox"><div class="mail-shadow"></div><div class="mail-post"></div>'
    + '<div class="mail-body"></div><div class="mail-flagpole"><div class="mail-flag"></div></div>'
    + '<div class="mail-roof"></div><div class="mail-slot"></div><div class="mail-emblem">✉</div></div>';

  function sceneHtml(preset) {
    const e = key => escapeHtml(t(key));
    switch (preset) {
      case 'email':
        return `<div class="scene email-scene">${CLOUDS}${item('envelope email-fly email-envelope')}`
          + `${desktop('<div class="incoming-email"></div>')}</div>`;
      case 'emailAR':
        return `<div class="scene email-scene ar-desktop">${CLOUDS}`
          + item('envelope email-fly email-envelope email-ar-fly', `<span class="email-ar-mark">${e('scene.arMark')}</span>`)
          + desktop(`<div class="receipt-card"><div class="receipt-check">✓</div><b>${e('scene.receiptTitle')}</b>`
            + `<small>${e('scene.receiptText')}</small></div>`)
          + '</div>';
      case 'postal':
        return `<div class="scene mail-scene">${CLOUDS}${item('envelope fly postal-envelope')}${MAILBOX}</div>`;
      case 'registered':
        return `<div class="scene mail-scene">${CLOUDS}`
          + item('registered', '<div class="envelope postal-envelope"></div><div class="registered-mark">✓</div>')
          + MAILBOX
          + `<div class="signature-card" data-label="${e('scene.receiptStamp')}"><div class="signature-line"></div>`
          + '<div class="signature-tick">✓</div></div></div>';
      case 'handDelivery':
        return `<div class="scene door-scene">${CLOUDS}`
          + item('handed', '<div class="folder-back"></div><div class="folder-paper"></div><div class="folder-front"></div><div class="hand-mark">🤝</div>')
          + '<div class="doorstep"><div class="mail-shadow"></div><div class="house-roof"></div><div class="house-wall">'
          + '<div class="house-window"></div><div class="house-window right"></div>'
          + '<div class="doorway"><div class="door-person"></div><div class="door-panel"></div></div></div>'
          + '<div class="door-step"></div></div>'
          + `<div class="signature-card" data-label="${e('scene.handedStamp')}"><div class="signature-line"></div>`
          + '<div class="signature-tick">✓</div></div></div>';
      case 'sms':
        return `<div class="scene sms-scene">${CLOUDS}<div class="sms-message">${e('scene.smsSample')}</div>`
          + `<div class="phone"><div class="phone-screen"><div class="notch"></div><div class="chat-head">${e('scene.smsApp')}</div>`
          + `<div class="bubble received">${e('scene.smsReceived')}</div><div class="bubble sent">${e('scene.smsSent')}</div>`
          + '<div class="home"></div></div></div></div>';
      case 'voice':
        return `<div class="scene voice-scene">${CLOUDS}`
          + item('call-signal', '<span></span>'.repeat(6), ` data-label="${e('scene.voiceMessage')}"`)
          + '<div class="phone call-phone"><div class="call-screen"><div class="call-top"></div>'
          + '<div class="call-wave"></div><div class="call-wave w2"></div><div class="avatar">☎</div>'
          + `<div class="caller-name">Pymissive</div><div class="call-status">${e('scene.incomingCall')}</div>`
          + '<div class="call-actions"><div class="call-action decline">✕</div><div class="call-action accept">☎</div></div>'
          + '</div></div></div>';
      case 'notification':
        return `<div class="scene notification-scene">${CLOUDS}${item('notice', `🔔 ${e('scene.noticeTitle')}`)}`
          + '<div class="phone"><div class="phone-screen home-screen"><div class="notch"></div>'
          + '<div class="status-bar"><span>9:41</span><span class="status-icons"><i></i><i></i><i></i><b></b></span></div>'
          + '<div class="app-grid">' + '<span class="app"></span>'.repeat(16) + '</div>'
          + '<div class="app-dock"><span class="app"><span class="app-badge">1</span></span>'
          + '<span class="app"></span>'.repeat(3) + '</div>'
          + `<div class="notice-banner"><span class="notice-bell">🔔</span><div><b>${e('scene.noticeTitle')}</b>`
          + `<small>${e('scene.noticeText')}</small></div></div><div class="home"></div></div></div></div>`;
      default:
        throw new Error('Unknown animation type: ' + preset);
    }
  }

  function elementFromHtml(html) {
    const template = document.createElement('template');
    template.innerHTML = html;
    return template.content.firstElementChild;
  }
  const sourceCache = Object.create(null);
  function sourceScene(preset) {
    if (!PRESETS[preset]) throw new Error('Unknown animation type: ' + preset);
    if (!sourceCache[preset]) sourceCache[preset] = elementFromHtml(sceneHtml(preset));
    return sourceCache[preset];
  }
  function cycleSeconds(root, preset) {
    const value = parseFloat(getComputedStyle(root).getPropertyValue(PRESETS[preset].cycleVar));
    return value > 0 ? value : 4;
  }
  function resolveHost(targetOrId) {
    const host = typeof targetOrId === 'string'
      ? document.getElementById(targetOrId.replace(/^#/, ''))
      : targetOrId;
    if (!host || !(host instanceof Element)) throw new Error('Container not found: ' + targetOrId);
    return host;
  }
  function applyColor(root, color) {
    if (color) root.style.setProperty('--pym-am-brand', String(color));
    else root.style.removeProperty('--pym-am-brand');
  }
  function createShell(targetOrId, color = null) {
    const host = resolveHost(targetOrId);
    // Mounting again into the same host must release the previous widget's observers.
    if (host.__animationMessagesApi) host.__animationMessagesApi.destroy();
    host.replaceChildren();
    const root = document.createElement('div');
    root.className = 'pym-am-root';
    applyColor(root, color ?? publicApi.color);
    const main = document.createElement('main');
    const grid = document.createElement('div');
    grid.className = 'grid single-card-grid';
    const card = document.createElement('section');
    card.className = 'card widget-single-card';
    grid.appendChild(card);
    main.appendChild(grid);
    root.appendChild(main);
    host.appendChild(root);
    return { host, root, card, cleanups: [], destroyed: false };
  }
  function integer(value, fallback = 0) {
    const n = Number(value);
    return Number.isFinite(n) ? Math.max(0, Math.floor(n)) : fallback;
  }
  function speedFactor(value) {
    const n = Number(value);
    return Number.isFinite(n) && n > 0 ? n : 1;
  }
  function messagesFrom(options) {
    if (Array.isArray(options.messages)) return options.messages.map(v => String(v).trim()).filter(Boolean);
    if (typeof options.message === 'string') return options.message.split(/\r?\n/).map(v => v.trim()).filter(Boolean);
    return [];
  }
  function shuffled(list) {
    const copy = list.slice();
    for (let i = copy.length - 1; i > 0; i--) {
      const j = Math.floor(Math.random() * (i + 1));
      const swap = copy[i];
      copy[i] = copy[j];
      copy[j] = swap;
    }
    return copy;
  }
  function textsForCount(messages, count) {
    if (!messages.length || count < 1) return [];
    const texts = [];
    while (texts.length < count) {
      const deck = shuffled(messages);
      for (let i = 0; i < deck.length && texts.length < count; i++) texts.push(deck[i]);
    }
    return texts;
  }
  function applyHeader(card, defaults, options) {
    const header = document.createElement('div');
    header.className = 'card-head';
    const icon = document.createElement('div');
    icon.className = 'icon';
    icon.textContent = options.icon != null ? String(options.icon) : defaults.icon;
    const texts = document.createElement('div');
    const title = document.createElement('h2');
    title.textContent = options.title != null ? String(options.title) : defaults.title;
    const subtitle = document.createElement('p');
    subtitle.textContent = options.subtitle != null ? String(options.subtitle) : defaults.subtitle;
    texts.append(title, subtitle);
    header.append(icon, texts);
    card.appendChild(header);
  }
  function addCounter(stage, options) {
    if (options.counter === false) return null;
    const total = integer(options.total, 100);
    const remaining = Math.min(total, integer(options.remaining, total));
    const panel = document.createElement('section');
    panel.className = 'lab-counter widget-card-counter';
    if (options.counterBackground === false) panel.classList.add('no-panel');
    panel.setAttribute('aria-label', t('counter.aria'));
    panel.innerHTML = '<div class="lab-counter-summary"><div><strong data-remaining-value></strong><span data-remaining-label></span></div><strong data-percent-value></strong></div><div class="lab-progress-track" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="0" data-progress-track><div class="lab-progress-fill" data-progress-fill></div></div><div class="lab-counter-result"><div class="lab-counter-summary"><div class="lab-result-sent"><strong data-sent-percent></strong><span data-sent-label></span></div><div class="lab-result-errors" data-errors><span data-errors-label></span><strong data-errors-percent></strong></div></div><div class="lab-progress-track lab-result-track" aria-hidden="true"><div class="lab-result-sent-fill" data-sent-fill></div><div class="lab-result-errors-fill" data-errors-fill></div></div></div>';
    stage.appendChild(panel);
    const nodes = {
      remaining: panel.querySelector('[data-remaining-value]'),
      label: panel.querySelector('[data-remaining-label]'),
      percent: panel.querySelector('[data-percent-value]'),
      track: panel.querySelector('[data-progress-track]'),
      fill: panel.querySelector('[data-progress-fill]'),
      sentPercent: panel.querySelector('[data-sent-percent]'),
      sentLabel: panel.querySelector('[data-sent-label]'),
      sentFill: panel.querySelector('[data-sent-fill]'),
      errorsBox: panel.querySelector('[data-errors]'),
      errorsPercent: panel.querySelector('[data-errors-percent]'),
      errorsLabel: panel.querySelector('[data-errors-label]'),
      errorsFill: panel.querySelector('[data-errors-fill]'),
      panel
    };
    nodes.track.setAttribute('aria-label', t('counter.progressAria'));
    nodes.label.textContent = ' ' + t('counter.remaining');
    let currentTotal = total;
    let currentRemaining = remaining;
    let currentErrors = integer(options.errors, 0);
    let summary = options.summary === true;
    function render(nextTotal = currentTotal, nextRemaining = currentRemaining) {
      currentTotal = integer(nextTotal);
      currentRemaining = Math.min(currentTotal, integer(nextRemaining));
      const done = currentTotal - currentRemaining;
      // Progress rounds down so 100 % only shows once everything is processed.
      const percent = currentTotal > 0 ? Math.floor(done / currentTotal * 1000) / 10 : 0;
      const errors = Math.min(currentErrors, done);
      const sent = done - errors;
      const finished = summary && currentTotal > 0 && currentRemaining === 0;
      nodes.remaining.textContent = formatNumber(currentRemaining);
      nodes.percent.textContent = formatPercent(percent) + ' ' + t('counter.processed');
      nodes.fill.style.width = percent + '%';
      nodes.track.setAttribute('aria-valuenow', String(percent));
      // Errors round up so a single error never shows as 0 %; sent is the rest, so both add up to 100 %.
      const errorsPercent = done > 0 ? Math.ceil(errors / done * 1000) / 10 : 0;
      const sentPercent = done > 0 ? Math.round((100 - errorsPercent) * 10) / 10 : 0;
      nodes.sentPercent.textContent = formatPercent(sentPercent);
      nodes.sentLabel.textContent = ' ' + t(sent > 1 ? 'counter.sentMany' : 'counter.sentOne');
      nodes.sentFill.style.width = sentPercent + '%';
      nodes.errorsPercent.textContent = formatPercent(errorsPercent);
      nodes.errorsLabel.textContent = t(errors > 1 ? 'counter.errorMany' : 'counter.errorOne') + ' ';
      nodes.errorsFill.style.width = errorsPercent + '%';
      nodes.errorsBox.classList.toggle('has-errors', errors > 0);
      nodes.panel.classList.toggle('is-summary', finished);
      nodes.panel.title = finished
        ? t('counter.summaryTitle', { sent: formatNumber(sent), errors: formatNumber(errors), total: formatNumber(currentTotal) })
        : t('counter.totalTitle', { total: formatNumber(currentTotal) });
      return { total: currentTotal, remaining: currentRemaining, done, percent, sent, errors, finished };
    }
    render();
    return {
      setTotal(value) { const total = integer(value); return render(total, Math.min(currentRemaining, total)); },
      setRemaining(value) { return render(currentTotal, value); },
      reset(value) { const total = integer(value); currentErrors = 0; return render(total, total); },
      update(remainingValue, totalValue, errorsValue) {
        if (errorsValue !== undefined) currentErrors = integer(errorsValue);
        return render(totalValue === undefined ? currentTotal : totalValue, remainingValue);
      },
      setErrors(value) { currentErrors = integer(value); return render(); },
      setSummary(enabled) { summary = Boolean(enabled); return render(); },
      setPanelBackground(enabled) { nodes.panel.classList.toggle('no-panel', !enabled); },
      setVisible(enabled) { nodes.panel.hidden = !enabled; },
      getState() { return render(); }
    };
  }
  function addCaption(stage, options, shell) {
    if (options.caption == null || String(options.caption) === '') return null;
    const caption = document.createElement('p');
    caption.className = 'lab-caption widget-card-caption';
    caption.textContent = String(options.caption);
    stage.appendChild(caption);
    const sync = () => {
      caption.style.height = 'auto';
      const height = Math.max(35, caption.scrollHeight + (caption.scrollHeight > 35 ? 12 : 0));
      caption.style.height = height + 'px';
      stage.style.setProperty('--lab-caption-zone', height + 'px');
      stage.style.setProperty('--lab-caption-extra', Math.max(0, height - 35) + 'px');
    };
    requestAnimationFrame(sync);
    if ('ResizeObserver' in global) {
      const observer = new ResizeObserver(sync);
      observer.observe(stage);
      shell.cleanups.push(() => observer.disconnect());
    } else {
      global.addEventListener('resize', sync);
      shell.cleanups.push(() => global.removeEventListener('resize', sync));
    }
    return caption;
  }
  function setSceneOptions(stage, options) {
    if (options.background === false) {
      stage.style.background = 'transparent';
      stage.querySelectorAll('.cloud').forEach(el => { el.style.display = 'none'; });
    }
    if (options.ground === false) stage.querySelectorAll('.ground').forEach(el => { el.style.display = 'none'; });
  }
  function staggerAnimations(items, cycle, speed) {
    const duration = cycle / speedFactor(speed);
    const step = duration / Math.max(1, items.length);
    items.forEach((el, i) => {
      el.style.animationDuration = duration + 's';
      el.style.animationDelay = (-i * step) + 's';
    });
  }
  function attachApi(shell, counter, extra = {}) {
    const api = {
      host: shell.host,
      root: shell.root,
      counter,
      setColor(color) { applyColor(shell.root, color); },
      destroy() {
        if (shell.destroyed) return;
        shell.destroyed = true;
        shell.cleanups.forEach(cleanup => cleanup());
        shell.host.replaceChildren();
        delete shell.host.__animationMessagesApi;
      },
      ...extra
    };
    shell.host.__animationMessagesApi = api;
    return api;
  }

  // Fraction of labTravel at which an item reaches the receiver.
  const ARRIVAL = 0.78;
  // Shortest loop of a receiver reaction: with faster arrivals it only reacts every few items.
  const MIN_REACTION_PERIOD = 1.5;
  const REACTIONS = '.incoming-email,.receipt-card,.signature-card,.notice-banner,.app-badge,.door-panel';

  function receiverParts(receiver) {
    if (receiver.html) return [elementFromHtml(receiver.html)];
    const scene = sourceScene(receiver.preset);
    const parts = [scene.querySelector(receiver.selector).cloneNode(true)];
    if (receiver.signature) parts.push(scene.querySelector(receiver.signature).cloneNode(true));
    return parts;
  }
  function eachMatch(parts, selector, callback) {
    parts.forEach(part => {
      if (part.matches(selector)) callback(part);
      part.querySelectorAll(selector).forEach(callback);
    });
  }
  // Times the receiver reactions so they fire as items arrive, whatever the count and speed.
  function syncReceiver(parts, duration, count) {
    const step = duration / count;
    const period = step * Math.max(1, Math.ceil(MIN_REACTION_PERIOD / step));
    const delay = ((ARRIVAL * (duration - period)) % period) - period;
    eachMatch(parts, REACTIONS, el => {
      el.style.animationDuration = period + 's';
      el.style.animationDelay = delay + 's';
    });
  }

  // types is one send type or an array of them; items cycle through the array in order.
  // options.receiver defaults to the matching receiver of a single type, or to the globe for a mix.
  function mountCard(targetOrId, types, options = {}) {
    const senderTypes = Array.isArray(types) ? types.slice() : [types];
    if (!senderTypes.length) throw new Error('At least one send type is required');
    senderTypes.forEach(type => { if (!PRESETS[type]) throw new Error('Unknown animation type: ' + type); });
    const first = senderTypes[0];
    const receiverType = options.receiver ?? (senderTypes.length === 1 ? PRESETS[first].receiver : 'globe');
    const receiver = RECEIVERS[receiverType];
    if (!receiver) throw new Error('Unknown receiver type: ' + receiverType);
    const native = senderTypes.length === 1 && PRESETS[first].receiver === receiverType;

    const shell = createShell(targetOrId, options.color);
    applyHeader(shell.card, native
      ? { title: t(first + '.title'), subtitle: t(first + '.subtitle'), icon: PRESETS[first].icon }
      : {
          title: senderTypes.map(type => t(type + '.title')).join(' + ') + ' → ' + t('receiver.' + receiverType),
          subtitle: t('combination.subtitle'),
          icon: PRESETS[first].icon
        }, options);
    const stage = document.createElement('div');
    stage.className = 'lab-stage' + (receiver.stageClass ? ' ' + receiver.stageClass : '');
    stage.setAttribute('aria-label', t('combination.aria'));
    stage.style.setProperty('--lab-end-x', receiver.endX);
    stage.style.setProperty('--lab-end-y', receiver.endY);
    stage.style.setProperty('--lab-end-scale', receiver.scale);
    const sceneContent = document.createElement('div');
    sceneContent.className = 'lab-scene-content';
    sceneContent.insertAdjacentHTML('beforeend', CLOUDS);
    const receiverNodes = receiverParts(receiver);
    receiverNodes[0].classList.add('lab-receiver');
    let messages = messagesFrom(options);
    function showReceivedMessage() {
      const incoming = receiverNodes[0].querySelector('.bubble.received');
      if (incoming && messages.length) incoming.textContent = messages[Math.floor(Math.random() * messages.length)];
    }
    showReceivedMessage();
    const caller = receiverNodes[0].querySelector('.caller-name');
    if (caller && options.callerName != null) caller.textContent = String(options.callerName).slice(0, 42);
    receiverNodes.forEach(node => sceneContent.appendChild(node));
    stage.appendChild(sceneContent);
    setSceneOptions(stage, options);
    shell.card.appendChild(stage);
    if (receiver.setup) receiver.setup(receiverNodes[0], shell);

    // Mixed types share the longest cycle so the stagger keeps items evenly spaced.
    const cycle = Math.max(...senderTypes.map(type => cycleSeconds(shell.root, type)));
    let speed = options.speed ?? 1;
    let items = [];
    function applyTexts() {
      const smsItems = items.filter(node => node.classList.contains('sms-message'));
      textsForCount(messages, smsItems.length).forEach((text, i) => { smsItems[i].textContent = text; });
    }
    // Measured after insertion so each item aims its own centre at the receiver centre.
    function measure() {
      items.forEach(node => {
        node.style.setProperty('--lab-item-half', (node.offsetWidth / 2) + 'px');
        node.style.setProperty('--lab-item-half-y', (node.offsetHeight / 2) + 'px');
      });
    }
    function animate() {
      staggerAnimations(items, cycle, speed);
      if (receiver.preset) {
        syncReceiver(receiverNodes, cycle / speedFactor(speed), items.length);
      }
    }
    function buildItems(desiredCount) {
      items.forEach(node => node.remove());
      const requested = Math.min(12, Math.max(1, integer(desiredCount, 3)));
      // Every type gets the same number of items, so none shows up more often than the others.
      const perType = Math.min(Math.floor(12 / senderTypes.length), Math.max(1, Math.round(requested / senderTypes.length)));
      items = [];
      for (let i = 0; i < perType * senderTypes.length; i++) {
        const type = senderTypes[i % senderTypes.length];
        const node = sourceScene(type).querySelector(PRESETS[type].selector).cloneNode(true);
        node.classList.add('lab-sender');
        items.push(node);
        sceneContent.appendChild(node);
      }
      applyTexts();
      animate();
      measure();
    }
    buildItems(options.count ?? 3);

    const caption = addCaption(stage, { caption: options.showCaption === false ? '' : options.caption }, shell);
    const counter = addCounter(stage, { ...options, counter: options.showCounter === false ? false : options.counter });
    const finale = document.createElement('div');
    finale.className = 'lab-finale';
    finale.hidden = true;
    finale.innerHTML = '<span class="lab-finale-mark" aria-hidden="true"></span><strong class="lab-finale-label"></strong>';
    stage.appendChild(finale);
    let finishTimer = 0;

    function finish(result = {}) {
      if (shell.destroyed || stage.classList.contains('is-finishing') || stage.classList.contains('is-finished')) return;
      const status = result.status === 'cancelled' ? 'cancelled' : 'completed';
      const errors = integer(result.errors, counter ? counter.getState().errors : 0);
      const hasErrors = status === 'completed' && errors > 0;
      const reducedMotion = global.matchMedia && global.matchMedia('(prefers-reduced-motion: reduce)').matches;
      const mark = finale.querySelector('.lab-finale-mark');
      const label = finale.querySelector('.lab-finale-label');
      const stateClass = status === 'cancelled' ? 'is-cancelled' : hasErrors ? 'has-errors' : 'is-completed';

      stage.classList.remove('is-cancelled', 'has-errors', 'is-completed');
      stage.classList.add('is-finishing', stateClass);
      mark.textContent = status === 'cancelled' ? '×' : hasErrors ? '!' : '✓';
      label.textContent = status === 'cancelled'
        ? t('end.cancelled')
        : t('end.sent') + (hasErrors ? ' — ' + formatNumber(errors) + ' ' + t(errors > 1 ? 'counter.errorMany' : 'counter.errorOne') : '');
      finale.hidden = false;

      if (status === 'completed' && !reducedMotion) {
        const finalSender = sourceScene(first).querySelector(PRESETS[first].selector).cloneNode(true);
        finalSender.classList.add('lab-sender', 'lab-final-sender');
        if (finalSender.classList.contains('sms-message') && messages.length) {
          finalSender.textContent = messages[Math.floor(Math.random() * messages.length)];
        }
        sceneContent.appendChild(finalSender);
        finalSender.style.setProperty('--lab-item-half', (finalSender.offsetWidth / 2) + 'px');
        finalSender.style.setProperty('--lab-item-half-y', (finalSender.offsetHeight / 2) + 'px');
      }

      const complete = () => {
        stage.querySelector('.lab-final-sender')?.remove();
        stage.classList.remove('is-finishing');
        stage.classList.add('is-finished');
        if (counter) counter.setSummary(true);
      };
      if (reducedMotion) complete();
      else {
        finishTimer = global.setTimeout(complete, status === 'cancelled' ? 450 : 1300);
        shell.cleanups.push(() => global.clearTimeout(finishTimer));
      }
    }

    return attachApi(shell, counter, {
      types: senderTypes.slice(),
      receiver: receiverType,
      caption,
      finish,
      setSpeed(value) {
        if (shell.destroyed) return;
        speed = value;
        animate();
      },
      setCount(value) {
        if (shell.destroyed) return;
        buildItems(value);
      },
      setMessages(values) {
        if (shell.destroyed) return;
        const list = Array.isArray(values) ? values : String(values).split(/\r?\n/);
        messages = list.map(v => String(v).trim()).filter(Boolean);
        applyTexts();
        measure();
        showReceivedMessage();
      },
      getState() { return { types: senderTypes.slice(), receiver: receiverType, count: items.length, hasCounter: Boolean(counter) }; }
    });
  }

  const publicApi = {
    presets: Object.keys(PRESETS),
    receivers: Object.keys(RECEIVERS),
    // Default brand color for widgets mounted afterwards; null keeps the stylesheet default.
    color: null,
    labels,
    setLabels,
    mount: mountCard,
    mountCard
  };
  global.PymissiveAnimation = publicApi;
})(window);
