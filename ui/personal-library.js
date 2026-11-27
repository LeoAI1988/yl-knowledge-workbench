'use strict';

(() => {
  function init() {
    const $ = id => document.getElementById(id);
    const tabs = ['map', 'works', 'quotes'];
    const step = 24;
    const detail = $('detail'), list = $('list'), more = $('more');
    const notice = $('notice'), search = $('search'), clip = $('clip');
    const cache = new Map(), trail = [];
    const workLoads = new Map(), workChecks = new Map();
    let quoteAttempt = 0, quoteWatch = null, quoteCheck = null, deferredReading = null;
    const ownHashEvents = new WeakSet();
    let host = null;
    try {
      if (window.parent !== window && window.parent.location.origin === location.origin) host = window.parent;
    } catch {}
    const tabOf = w => tabs.find(t => w.location.hash === '#' + t);
    const fresh = mode => ({mode, domain: null, topic: null, scopeKind: 'works', q: '', count: step, page: null, card: null});
    let state = fresh(tabOf(window) || (host && tabOf(host)) || 'map');
    let catalog = null, globalRevision, domains = [], works = [], quotes = [];
    let workById = new Map(), quoteById = new Map(), refsByWork = new Map();
    let draft = null, reader = null, pending = null, viewKey = '', listKey = '', scopeKey = '';
    let epoch = 0, mutation = 0, busy = 0, writing = false, polling = false, syncingHash = false;
    let focusTimer;

    const array = a => Array.isArray(a) ? a : [];
    const str = v => v == null ? '' : String(v);
    const idOf = (kind, item) => str(kind === 'works' ? item.source_id : item.id);
    const tagged = (item, field, id) => id == null || array(item[field]).some(v => str(v) === id);
    const keyOf = (kind, id) => JSON.stringify([kind, id]);
    const number = n => new Intl.NumberFormat('zh-CN').format(Number(n) || 0);
    const missing = e => e.status === 404 || /来源已移除|来源不可用|没有找到金句|金句已移除|没有这份可用|找不到指定的文件|No such file/i.test(e.message);

    function el(tag, text, cls) {
      const node = document.createElement(tag);
      if (text != null) node.textContent = text;
      if (cls) node.className = cls;
      return node;
    }
    function group(cls, ...nodes) {
      const node = el('div', null, cls);
      node.append(...nodes);
      return node;
    }
    const hint = text => el('p', text, 'hint');
    function button(text, fn, cls, key) {
      const b = el('button', text, cls);
      b.type = 'button';
      if (key) b.dataset.focusKey = key;
      b.onclick = () => run(fn);
      return b;
    }
    function message(text = '', error = false) {
      notice.classList.toggle('error', error);
      notice.replaceChildren();
      if (text) notice.append(document.createTextNode(text));
      if (draft?.conflict) {
        const original = draft;
        notice.append(document.createTextNode((text ? ' ' : '') +
          (original.conflict === 'removed'
            ? '另一端已移除这份正文。当前草稿已保留。 '
            : '另一端已校订这份正文。当前草稿已保留，不能覆盖旧版本。 ')));
        notice.append(button('确认并读取最新', async () => {
          if (draft !== original || writing || !confirm('放弃尚未保存的输入，读取最新状态？')) return;
          try {
            const record = await fetchWork(original.id);
            if (draft !== original) return;
            cache.set(original.id, record);
            draft = null;
            ++epoch;
            viewKey = '';
            renderPage(false);
            message('已读取最新正文。');
          } catch (e) {
            if (draft !== original) return;
            if (!missing(e)) throw e;
            cache.delete(original.id);
            draft = null;
            ++epoch;
            setDetail('removed', [hint('正文已移除。可以返回浏览列表。')]);
            message('正文已移除。');
          }
        }, 'text-button', 'read-latest'));
      }
    }
    async function run(fn) {
      ++busy;
      try { await fn(); }
      catch (e) { message(e?.message || '操作失败，请重试。', true); }
      finally { --busy; }
    }
    async function api(action, params = {}) {
      const r = await fetch('/api/personal-library', {
        method: 'POST',
        headers: {'Content-Type': 'application/json', 'X-Knowledge-Client': 'workbench'},
        body: JSON.stringify({action, ...params})
      });
      let data;
      try { data = await r.json(); } catch {}
      if (!r.ok || !data?.ok) {
        throw Object.assign(new Error(data?.error || '请求失败（' + r.status + '）'), {status: r.status});
      }
      return data;
    }

    function syncHash() {
      if (syncingHash) return;
      syncingHash = true;
      try {
        for (const w of [window, host]) {
          if (!w || (w !== window && w.location.hash && !tabOf(w))) continue;
          const hash = '#' + state.mode;
          if (w.location.hash === hash) continue;
          const oldURL = w.location.href;
          try {
            w.history.replaceState(w.history.state, '', hash);
            const event = new w.HashChangeEvent('hashchange', {oldURL, newURL: w.location.href});
            ownHashEvents.add(event);
            w.dispatchEvent(event);
          } catch {}
        }
      } finally { syncingHash = false; }
    }
    function onHash(w, event) {
      if (syncingHash || ownHashEvents.has(event)) return;
      const mode = tabOf(w);
      if (mode && mode !== state.mode) run(() => switchTab(mode));
    }

    function position() {
      const active = document.activeElement;
      return {
        x: window.scrollX, y: window.scrollY, list: list.scrollTop, detail: detail.scrollTop,
        focus: active?.id || null, key: active?.dataset.focusKey || null
      };
    }
    function restore(pos) {
      if (!pos) return;
      const target = (pos.focus && $(pos.focus)) ||
        (pos.key && Array.from(document.querySelectorAll('[data-focus-key]')).find(n => n.dataset.focusKey === pos.key));
      if (target && !target.closest('[hidden]') && !target.disabled) target.focus({preventScroll: true});
      list.scrollTop = pos.list;
      detail.scrollTop = pos.detail;
      window.scrollTo(pos.x, pos.y);
    }
    function preserve(fn) {
      const pos = position();
      fn();
      restore(pos);
    }
    function mayLeave() {
      return !writing && (!draft?.dirty || confirm('放弃尚未保存的输入？'));
    }
    function resetReader() {
      deferredReading = null;
      reader = null;
      pending = null;
      clip.hidden = true;
    }
    function setDetail(key, nodes) {
      if (key === viewKey) return false;
      viewKey = key;
      resetReader();
      detail.replaceChildren(...nodes);
      return true;
    }
    function navigate(next, {push = true, pos = null, force = false} = {}) {
      if (!force && !mayLeave()) { syncHash(); return; }
      if (push) trail.push({state: {...state}, pos: position()});
      state = next;
      search.value = next.q;
      draft = null;
      viewKey = '';
      resetReader();
      ++epoch;
      message();
      syncHash();
      renderShell();
      if (pos) restore(pos);
      else {
        window.scrollTo(0, 0);
        detail.scrollTop = list.scrollTop = 0;
      }
      const rendered = renderPage(true, pos);
      if (pos) restore(pos);
      return rendered;
    }
    function back() {
      if (!trail.length || !mayLeave()) return;
      const entry = trail.pop();
      return navigate(entry.state, {push: false, pos: entry.pos, force: true});
    }
    function home() {
      if (!mayLeave()) return;
      trail.length = 0;
      return navigate(fresh('map'), {push: false, force: true});
    }
    function switchTab(mode) {
      const alreadyThere = mode === state.mode && !state.page && !draft;
      const unfiltered = state.domain === null && state.topic === null && state.q === '';
      if (alreadyThere && (mode === 'map' || unfiltered)) { syncHash(); return; }
      return navigate(fresh(mode));
    }
    function setScope(domain, topic) {
      if (state.domain === domain && state.topic === topic && !state.page && !draft) return;
      const q = state.mode === 'map' && domain === null ? '' : state.q;
      return navigate({...state, domain, topic, q, count: step, card: null, page: null});
    }
    function openCard(kind, id) {
      if (!mayLeave()) return;
      state.card = keyOf(kind, id);
      markCards();
      const pos = position();
      pos.focus = null;
      pos.key = 'tile:' + state.card;
      const result = navigate({...state, page: {kind, id}}, {force: true});
      trail[trail.length - 1].pos = pos;
      return result;
    }
    function openSource(ref, quoteId) {
      const page = state.page;
      if (page?.kind !== 'quotes' || page.id !== quoteId) return;
      return navigate({...state, page: {kind: 'quotes', id: quoteId, source: ref?.source}}, {push: false});
    }

    function reference(q, ref = q) {
      const source = str(ref.source_id);
      const line = Number(ref.start_line);
      if (!source) return null;
      return {
        source, title: str(ref.source_title), line: Number.isSafeInteger(line) && line > 0 ? line : null,
        text: str(ref.actual_text || ref.text), context: str(ref.context || (ref === q ? q.context : '')),
        quote: str(q.id)
      };
    }
    function references(q) {
      return Array.from(new Map([q, ...array(q.variants)].map(r => reference(q, r)).filter(Boolean)
        .map(r => [JSON.stringify([r.source, r.line, r.text]), r])).values());
    }
    function installCatalog(data) {
      catalog = data.item || {};
      globalRevision = data.revision?.global;
      domains = array(catalog.domains);
      works = array(catalog.works);
      quotes = array(catalog.quotes);
      workById = new Map(works.map(w => [str(w.source_id), w]));
      quoteById = new Map(quotes.map(q => [str(q.id), q]));
      refsByWork = new Map();
      for (const q of quotes) {
        for (const ref of references(q)) {
          if (!refsByWork.has(ref.source)) refsByWork.set(ref.source, []);
          refsByWork.get(ref.source).push(ref);
        }
      }
      const stats = catalog.stats || {};
      const characters = Math.max(0, Math.trunc(Number(stats.characters) || 0));
      const inWan = characters >= 10000;
      const headline = el('span', null, 'kb-stats-headline');
      headline.append('已收录 ', el('strong', inWan ? (characters / 10000).toFixed(1) : number(characters), 'kb-stats-total'), inWan ? ' 万字' : ' 字');
      const counts = el('span', `${number(stats.works ?? works.length)} 篇正文 · ${number(stats.quotes ?? quotes.length)} 条金句`, 'kb-stats-counts');
      $('stats').replaceChildren(headline, counts);
    }
    function domainOf(id) { return domains.find(d => str(d.id) === id); }
    function topicOf() {
      return array(domainOf(state.domain)?.topics).find(t => str(t.id) === state.topic) ||
        domains.flatMap(d => array(d.topics)).find(t => str(t.id) === state.topic);
    }
    function domainTopics(domain) {
      const domainId = str(domain.id);
      return array(domain.topics).map(topic => ({
        topic,
        count: rowsFor('works', domainId, str(topic.id)).length
      }));
    }
    function renderScope() {
      const key = JSON.stringify([state.domain, state.topic, domains]);
      if (key === scopeKey) return;
      scopeKey = key;
      const d = domainOf(state.domain), t = topicOf();
      const domainSelect = el('select');
      domainSelect.setAttribute('aria-label', '筛选领域');
      domainSelect.dataset.focusKey = 'domain-filter';
      domainSelect.append(new Option('全部领域', ''));
      for (const item of domains) domainSelect.append(new Option(str(item.title), str(item.id)));
      if (state.domain !== null && !d) domainSelect.append(new Option('当前领域已不可用', state.domain));
      domainSelect.value = state.domain ?? '';
      domainSelect.onchange = () => {
        const id = domainSelect.value || null;
        domainSelect.value = state.domain ?? '';
        run(() => setScope(id, null));
      };
      const parts = [el('span', [d?.title || (state.domain === null ? '全库' : '当前领域已不可用'),
        t?.title || (state.topic === null ? '全部话题' : '当前话题已不可用')].join(' / ')), domainSelect];
      if (state.topic !== null) parts.push(button('清除话题', () => setScope(state.domain, null), 'text-button', 'clear-topic'));
      if (state.domain !== null || state.topic !== null) parts.push(button('切回全部', () => setScope(null, null), 'text-button', 'clear-scope'));
      $('scope').replaceChildren(...parts);
    }
    function renderShell() {
      for (const tab of tabs) $(tab).setAttribute('aria-pressed', String(state.mode === tab));
      $('home').setAttribute('aria-label', '知识库首页');
      $('home').title = '首页';
      $('back').setAttribute('aria-label', '返回');
      $('back').title = '上一步';
      $('back').disabled = !trail.length;
      const browsing = !state.page && !draft;
      const atMapRoot = state.mode === 'map' && state.domain === null;
      $('stats').hidden = !catalog || !browsing || !atMapRoot || state.topic !== null;
      $('scope').hidden = !browsing || atMapRoot;
      $('new').hidden = !browsing || state.mode === 'map' || state.domain !== null || state.topic !== null;
      $('toolbar').hidden = !browsing || atMapRoot;
      const kind = state.mode === 'map' ? (state.scopeKind || 'works') : state.mode;
      search.placeholder = kind === 'quotes' ? '搜索金句' : '搜索作品';
      $('new').textContent = state.mode === 'works' ? '新增正文' : '从正文补收';
      renderScope();
      renderList();
    }
    function markCards() {
      for (const b of list.querySelectorAll('[data-item]')) {
        if (b.dataset.item === state.card) b.setAttribute('aria-current', 'true');
        else b.removeAttribute('aria-current');
      }
    }
    function rowsFor(kind, domain = state.domain, topic = state.topic, q = state.q) {
      const query = q.trim().toLocaleLowerCase();
      const result = [], seen = new Set();
      const isWork = kind === 'works';
      for (const item of isWork ? works : quotes) {
        if (!tagged(item, 'domains', domain) || !tagged(item, 'topics', topic)) continue;
        const id = idOf(kind, item);
        if (!id || seen.has(id)) continue;
        const title = isWork ? (str(item.title).trim() || '未命名作品') :
          (str(item.text).trim() || str(item.actual_text).trim());
        if (!title) continue;
        const rawPreview = isWork ? str(item.preview).trim() : '';
        if (query) {
          const labels = domains.filter(d => tagged(item, 'domains', str(d.id))).map(d => d.title);
          const topicLabels = domains.flatMap(d => array(d.topics))
            .filter(t => tagged(item, 'topics', str(t.id))).map(t => t.title);
          const metadata = isWork ? ['作品', number(item.characters) + ' 字'] :
            ['金句', item.context, item.actual_text, item.source_title, item.selected ? '亲选' : '',
              item.source_id ? '有来源' : '无可用出处'];
          if (![title, rawPreview, ...metadata, ...labels, ...topicLabels].join('\n').toLocaleLowerCase().includes(query)) continue;
        }
        let preview = '';
        if (rawPreview) {
          let end = rawPreview.length, sentences = 0;
          for (const match of rawPreview.matchAll(/[。！？!?]+|\.(?=\s|$)/gu)) {
            if (++sentences === 3) { end = match.index + match[0].length; break; }
          }
          const opening = Array.from(rawPreview.slice(0, end));
          preview = opening.length > 280 ? opening.slice(0, 280).join('').trimEnd() + '…' : opening.join('');
        }
        seen.add(id);
        result.push({kind, id, title, preview});
      }
      return result;
    }
    function tile(row) {
      const key = keyOf(row.kind, row.id);
      const isWork = row.kind === 'works';
      const b = button(null, () => openCard(row.kind, row.id), 'tile ' + (isWork ? 'kb-work-tile' : 'kb-quote-tile'), 'tile:' + key);
      b.dataset.item = key;
      if (isWork) {
        b.append(el('strong', row.title, 'tile-title'));
        if (row.preview) b.append(el('span', row.preview, 'tile-preview'));
      } else {
        b.append(el('span', row.title, 'kb-quote-text'));
      }
      return b;
    }
    function renderList() {
      const visible = !state.page && !draft && (state.mode !== 'map' || state.domain !== null);
      list.hidden = !visible;
      more.hidden = true;
      if (!visible) {
        if (listKey) list.replaceChildren();
        listKey = '';
        return;
      }
      const kind = state.mode === 'map' ? (state.scopeKind || 'works') : state.mode;
      const label = kind === 'works' ? '作品正文列表' : '金句列表';
      if (list.getAttribute('aria-label') !== label) {
        list.setAttribute('role', 'region');
        list.setAttribute('aria-label', label);
      }
      const rows = catalog ? rowsFor(kind) : [];
      const key = JSON.stringify([kind, !!catalog, rows]);
      if (key !== listKey) {
        list.replaceChildren(...(rows.length ? rows.map(tile) : [hint(catalog ? '没有匹配的内容。' : '正在读取目录…')]));
        listKey = key;
      }
      markCards();
    }
    function mapPage() {
      if (!catalog) {
        setDetail('catalog-loading', [hint('正在读取知识库…')]);
        return;
      }
      const domain = domainOf(state.domain);
      if (!domain) {
        const entries = domains.map(d => {
          const id = str(d.id);
          return [d, rowsFor('works', id, null, '').length, rowsFor('quotes', id, null, '').length];
        });
        const key = 'map:' + JSON.stringify([state.domain, entries]);
        if (key === viewKey) return;
        const cards = entries.map(([d, workCount, quoteCount]) => {
          const id = str(d.id);
          const b = button(null, () => setScope(id, null), 'domain-card', 'domain:' + id);
          b.append(el('strong', d.title, 'tile-title'),
            el('span', ({ai:'人工智能、个人能力与知识系统',media:'媒体、流量、修辞、心理与社会',architecture:'建筑、文化、文明与历史',business:'公司、组织、创业与经营'})[id], 'tile-preview'),
            el('small', `${number(workCount)} 篇正文 · ${number(quoteCount)} 条金句`, 'tile-meta'));
          return b;
        });
        setDetail(key, [
          el('h2', '按领域浏览'),
          ...(state.domain !== null ? [hint('当前领域已不可用，请切回全部或选择其他领域。')] : []),
          cards.length ? group('domains', ...cards) : hint('尚未整理领域。可直接浏览作品或金句。')
        ]);
        return;
      }
      const domainId = str(domain.id);
      const topics = domainTopics(domain);
      const activeKind = state.scopeKind || 'works';
      const counts = [rowsFor('works').length, rowsFor('quotes').length];
      const key = 'domain:' + JSON.stringify([domainId, domain.title, topics, state.topic, activeKind, counts]);
      if (key === viewKey) return;
      const chips = topics.map(({topic, count}) => {
        const id = str(topic.id);
        const b = button(`${topic.title} · ${number(count)} 篇正文`, () => setScope(domainId, id), 'topic-chip', 'topic:' + id);
        b.setAttribute('aria-pressed', String(state.topic === id));
        return b;
      });
      const all = button('全部话题', () => setScope(domainId, null), 'topic-chip', 'all-topics');
      all.setAttribute('aria-pressed', String(state.topic === null));
      const topicPicker = group('topics kb-topic-picker', all, ...chips);
      topicPicker.setAttribute('role', 'group');
      topicPicker.setAttribute('aria-label', '选择话题（数量为当前搜索下的正文篇数）');
      const kinds = group('scope-links kb-scope-kinds', ...[['works', '作品正文'], ['quotes', '金句']].map(([kind, label], i) => {
        const b = button(`${label} ${number(counts[i])}`, () => {
          if (state.mode !== 'map' || state.domain !== domainId || state.page || draft || (state.scopeKind || 'works') === kind) return;
          state = {...state, scopeKind: kind, card: null};
          preserve(() => { renderShell(); mapPage(); });
        }, 'kb-scope-kind', 'scope-' + kind);
        b.setAttribute('aria-pressed', String(activeKind === kind));
        b.setAttribute('aria-controls', 'list');
        return b;
      }));
      kinds.setAttribute('role', 'group');
      kinds.setAttribute('aria-label', '切换当前范围的内容类型');
      if (state.topic === null) {
        setDetail(key, [
          el('h2', domain.title),
          el('h3', '选择话题', 'kb-topic-caption'),
          topicPicker,
          ...(chips.length ? [] : [hint('此领域暂无话题。')]),
          el('h3', '全部话题', 'kb-active-topic'),
          kinds
        ]);
        return;
      }
      const pickerScope = JSON.stringify([domainId, state.topic]);
      const previous = detail.querySelector('.kb-topic-switcher');
      const picker = el('details', null, 'kb-topic-switcher');
      picker.dataset.pickerScope = pickerScope;
      picker.open = previous?.dataset.pickerScope === pickerScope && previous.open;
      const summary = el('summary', '切换话题');
      summary.dataset.focusKey = 'switch-topic';
      picker.append(summary, topicPicker);
      const title = el('h2', topicOf()?.title || '当前话题已不可用', 'kb-active-topic');
      setDetail(key, [group('kb-topic-bar', title, picker), kinds]);
    }

    function writeFrom(kind, id) {
      window.parent.postMessage({type: 'yl-write-from-library', kind, id}, location.origin);
    }
    async function refreshAfterWrite(next, text, result, push = true, pos = null) {
      let catalogError;
      try { installCatalog(await api('library.catalog')); }
      catch (e) { catalogError = e; }
      if (result?.source_id && Array.isArray(result.readable_blocks || result.blocks) && result.hash) {
        cache.set(str(result.source_id), {item: result, revision: null, at: globalRevision});
      }
      await navigate(next, {force: true, push, pos});
      if (catalogError) message(text + '目录暂未更新，将自动重试。', true);
      else if (!notice.classList.contains('error')) message(text);
    }
    async function write(action, params, after) {
      if (writing) return;
      if (draft?.conflict) { message('请先处理版本冲突。', true); return; }
      const original = draft;
      writing = true;
      ++mutation;
      message();
      try {
        let result;
        try { result = await api(action, params); }
        catch (e) {
          if (original?.id) {
            try { await checkDraft(original, () => draft === original); } catch {}
          }
          throw e;
        }
        await after(result);
      } finally { writing = false; }
    }
    function openAddedQuote(result, text) {
      const id = str(result.item?.id);
      const previous = trail[trail.length - 1];
      const fromQuoteList = isQuoteList(previous?.state);
      const entry = fromQuoteList ? previous : quoteListEntry();
      if (!id) return refreshAfterWrite(entry.state, text, null, false, entry.pos);
      if (!fromQuoteList) {
        if (!draft) trail.push({state: {...state}, pos: position()});
        trail.push(entry);
      }
      return refreshAfterWrite({...entry.state, card: keyOf('quotes', id), page: {kind: 'quotes', id}}, text, null, false);
    }
    async function quotePage(page, foreground = false, restorePos = null) {
      const token = epoch, version = mutation, attempt = ++quoteAttempt;
      const q = quoteById.get(page.id);
      const valid = () => token === epoch && version === mutation && attempt === quoteAttempt &&
        state.page === page && !draft && quoteById.get(page.id) === q;
      const background = !foreground;
      if (!q) {
        quoteWatch = null;
        const key = 'quote-missing:' + JSON.stringify([page.id, !!catalog]);
        paintReading(page, key, background, () => setDetail(key, [hint(catalog
          ? '这句金句已移除或暂不可用。可以返回金句列表。' : '正在读取金句目录…')]));
        return;
      }
      const titleOf = ref => workById.get(ref.source)?.title || ref.title || '未命名作品';
      const refs = rankedQuoteRefs(q);
      const bySource = new Map();
      for (const ref of refs) if (!bySource.has(ref.source)) bySource.set(ref.source, ref);
      const checked = new Map();
      async function locate(candidates) {
        for (const ref of candidates) {
          if (!valid()) return null;
          if (!checked.has(ref.source)) checked.set(ref.source, loadWork(ref.source).then(record =>
            ({item: record.item, blocks: readable(record.item)}), e => {
            if (!missing(e)) throw e;
            return null;
          }));
          const source = await checked.get(ref.source);
          if (!valid()) return null;
          if (!source) continue;
          const count = source.blocks.reduce((n, b) => n + offsets(b, ref).length, 0);
          if (count === 1) return {...source, ref};
        }
        return null;
      }
      if (foreground) setDetail('quote-loading:' + page.id, [
        el('h2', q.text, 'quote-heading'), hint('正在核对出处并读取完整正文…')
      ]);
      let main, current, failure;
      try {
        main = await locate(refs);
        if (!valid()) return;
        current = !page.source || page.source === main?.ref.source
          ? main : await locate(refs.filter(ref => ref.source === page.source));
      } catch (e) { failure = e; }
      if (!valid()) return;
      quoteWatch = {page, sources: [...checked.keys()]};
      if (failure && background && reader) return;
      const actions = [];
      const actionRef = (main || current)?.ref;
      if (actionRef) actions.push(button('金句用于写作', () =>
        withCurrentQuoteSource(page, actionRef, false, () => writeFrom('quote', page.id)), null, 'quote-write'));
      if (!q.selected && actionRef) actions.push(button('保留为亲选', () =>
        withCurrentQuoteSource(page, actionRef, true, (item, ref) =>
          write('quotes.add', {source_id: ref.source, expected_hash: item.hash,
            start_line: ref.line, text: ref.text}, r => {
            const id = str(r.item?.id) || page.id;
            return refreshAfterWrite({...state, card: keyOf('quotes', id),
              page: id === page.id ? page : {kind: 'quotes', id}}, '已标为亲选。', null, false);
          })), 'primary', 'quote-select'));
      actions.push(button('移除／疑似误收', () => {
        if (state.page !== page || !quoteById.has(page.id) ||
          !confirm('移除这句金句并记住此次选择？作品正文中的原话会保留。')) return;
        return write('quotes.remove', {id: page.id}, () => {
          const previous = trail[trail.length - 1];
          const entry = previous && !previous.state.page ? trail.pop() : quoteListEntry();
          return refreshAfterWrite({...entry.state, card: null}, '已移除并记住此次选择。', null, false, entry.pos);
        });
      }, 'danger', 'quote-remove'));
      const ordered = main ? [main.ref, ...[...bySource.values()].filter(r => r.source !== main.ref.source)]
        : [...bySource.values()];
      const citations = el('nav', null, 'quote-citations');
      citations.setAttribute('aria-label', '切换金句出处');
      if (ordered.length) {
        citations.append(el('h3', main ? '金句出处' : '待核对的收录出处'));
        const items = el('ul');
        for (const ref of ordered) {
          const primary = ref.source === main?.ref.source;
          const active = ref.source === (page.source || main?.ref.source);
          const b = button((primary ? '主推 · ' : '') + titleOf(ref),
            () => { if (state.page === page && !active) return openSource(primary ? null : ref, page.id); },
            'text-button', 'quote-source:' + ref.source);
          if (active) b.setAttribute('aria-current', 'true');
          const li = el('li');
          li.append(b);
          items.append(li);
        }
        citations.append(items);
      }
      const status = failure ? '暂时无法完成出处核对，可以重试。' : current
        ? (current.ref.text === q.text ? '已在正文定位原话。' : '已在正文定位该作品中的实际变体。')
        : page.source ? '所选出处已不可用，或当前正文无法唯一定位收录措辞。'
          : '暂无能在可读正文中唯一定位的已核实出处。';
      const heading = el('h2', q.text, 'quote-heading');
      const toolbar = [hint((q.selected ? '已亲选 · ' : '') + status), group('actions', ...actions)];
      const tail = ordered.length ? [citations] : [];
      const signature = [q, main?.ref, page.source, ordered.map(r => [r.source, titleOf(r)]), status];
      if (current) {
        const targetChanged = !reader || reader.targetKey !== JSON.stringify(current.ref);
        const jump = !restorePos && (foreground || targetChanged) && (!background || targetChanged);
        displayWork(current.item, page, jump, {background, quote: {heading, toolbar, tail,
          signature, ref: current.ref, blocks: current.blocks}});
      } else {
        const key = 'quote-unlocated:' + JSON.stringify(signature);
        paintReading(page, key, background, () => setDetail(key, [heading, ...toolbar,
          ...(failure ? [button('重试', () => quotePage(page, true), null, 'retry-quote')] : []), ...tail]));
      }
      if (restorePos) restore(restorePos);
    }

    function isQuoteList(s) {
      return !!s && !s.page && (s.mode === 'quotes' || (s.mode === 'map' && s.scopeKind === 'quotes'));
    }
    function quoteListEntry() {
      for (let i = trail.length - 1; i >= 0; i--) {
        const entry = trail[i];
        if (isQuoteList(entry.state) &&
          entry.state.domain === state.domain && entry.state.topic === state.topic) return entry;
      }
      return {state: {...state, mode: 'quotes', page: null, card: null},
        pos: {x: 0, y: 0, list: 0, detail: 0, focus: null, key: null}};
    }
    async function withCurrentQuoteSource(page, shown, selecting, action) {
      const token = epoch, version = mutation;
      const active = () => state.page === page && token === epoch && version === mutation && !draft && !writing;
      if (!active()) return;
      const {revision: quoteRev} = await api('library.revision', {watch: 'quotes:' + page.id});
      if (!active()) return;
      if (quoteCheck?.id !== page.id || !sameRevision(quoteCheck.revision, quoteRev) ||
        !Object.is(globalRevision, quoteRev?.global)) {
        const data = await api('library.catalog');
        if (!active()) return;
        installCatalog(data);
        if (quoteRev && Object.is(globalRevision, quoteRev.global)) quoteCheck = {id: page.id, revision: quoteRev};
      }
      const currentRef = q => q && references(q).find(r =>
        r.source === shown.source && r.line === shown.line && r.text === shown.text);
      let latest = quoteById.get(page.id);
      if (!latest || (selecting && latest.selected)) return quotePage(page);
      if (!currentRef(latest)) {
        await quotePage(page);
        if (active()) message('这句的收录出处已更新，请核对后再操作。', true);
        return;
      }
      const at = globalRevision;
      const {revision: sourceRev} = await api('library.revision', {watch: 'works:' + shown.source});
      if (!active()) return;
      if (!sourceRev || !Object.is(sourceRev.global, at) || !Object.is(globalRevision, at)) {
        throw new Error('目录或正文版本已变化，请稍后重试。');
      }
      checkWorkWatch(shown.source, sourceRev);
      const {item, revision} = await loadWork(shown.source);
      if (!active()) return;
      latest = quoteById.get(page.id);
      if (!latest || (selecting && latest.selected)) return quotePage(page);
      const ref = currentRef(latest);
      if (!Object.is(globalRevision, at) ||
        (revision?.global != null && !Object.is(revision.global, sourceRev.global)) ||
        (revision?.detail != null && !Object.is(revision.detail, sourceRev.detail))) {
        throw new Error('目录或正文版本已变化，请稍后重试。');
      }
      if (!ref || (selecting && !item.hash) ||
        readable(item).reduce((n, b) => n + offsets(b, ref).length, 0) !== 1) {
        throw new Error('当前正文已无法唯一定位这句，请核对出处后再操作。');
      }
      return action(item, ref);
    }
    function rankedQuoteRefs(q) {
      const compare = (a, b) => a < b ? -1 : a > b ? 1 : 0;
      const rank = (ref, field, id) => Number(id != null && tagged(workById.get(ref.source) || {}, field, id));
      return references(q).filter(r => r.line && r.text).sort((a, b) =>
        rank(b, 'topics', state.topic) - rank(a, 'topics', state.topic) ||
        rank(b, 'domains', state.domain) - rank(a, 'domains', state.domain) ||
        Number(b.text === q.text) - Number(a.text === q.text) ||
        compare(a.source, b.source) || a.line - b.line || compare(a.text, b.text) ||
        compare(a.context, b.context) || compare(a.title, b.title));
    }
    function cachedWork(id) {
      const record = cache.get(id);
      return record && Object.is(record.at, globalRevision) ? record : null;
    }
    async function loadWork(id) {
      let record = cachedWork(id);
      if (!record) {
        const at = globalRevision, watch = workChecks.get(id);
        try { record = {...await fetchWork(id), watch}; }
        catch (e) {
          if (!missing(e)) throw e;
          record = {error: e, at, watch};
        }
        if (Object.is(at, globalRevision) && watch === workChecks.get(id)) cache.set(id, record);
      }
      if (record.error) throw record.error;
      return record;
    }
    function checkWorkWatch(id, revision) {
      if (!revision || !Object.is(revision.global, globalRevision)) return;
      const record = cachedWork(id);
      const known = record?.revision?.detail != null ? record.revision : record?.watch;
      if (sameRevision(workChecks.get(id), revision)) revision = workChecks.get(id);
      workChecks.set(id, revision);
      if (record && !sameRevision(known, revision)) cache.delete(id);
    }
    function holdsReadingSelection() {
      const selection = window.getSelection();
      if (!reader || !selection || selection.isCollapsed) return false;
      for (let i = 0; i < selection.rangeCount; i++) {
        if (selection.getRangeAt(i).intersectsNode(reader.article)) return true;
      }
      return false;
    }
    function paintReading(page, key, background, paint) {
      if (state.page !== page || draft) return;
      if (key === viewKey) {
        deferredReading = null;
        if (pending) clip.hidden = false;
        return;
      }
      if (background && holdsReadingSelection()) {
        deferredReading = {page, apply: () => paintReading(page, key, true, paint)};
        pending = null;
        clip.hidden = true;
        return;
      }
      deferredReading = null;
      if (background) preserve(paint);
      else paint();
    }
    function showWorkError(page, error, background, restorePos) {
      const key = 'work-error:' + JSON.stringify([page.id, missing(error)]);
      paintReading(page, key, background, () => setDetail(key, [
        hint(missing(error) ? '这份正文已移除或不可用，可以返回。' : '读取正文失败，可以重试或返回。'),
        button('重试', () => {
          if (cachedWork(page.id)?.error) cache.delete(page.id);
          return renderPage(true, restorePos);
        }, null, 'retry-work')
      ]));
    }
    function readingMetadata(info) {
      const clean = value => typeof value === 'string' ? value.trim() : '';
      const first = (...values) => values.map(clean).find(Boolean) || '';
      const internal = '(?:反共识立场|反共识观点|IP\\s*灵魂|IP\\s*人设|内部分析|分析标签|爆款要素|传播要素|情绪钩子|传播机制|用户痛点|核心冲突|内容钩子|记忆点|情绪价值|目标受众)';
      const prefix = new RegExp('^(?:[【\\[（(]\\s*' + internal + '\\s*[】\\]）)]\\s*[:：·—-]?\\s*|' + internal + '(?:\\s*[/／、]\\s*' + internal + ')*\\s*[:：·—-]\\s*)', 'iu');
      const unresolved = new RegExp(internal, 'iu');
      const highlights = [...new Set(array(info?.highlights).map(value => {
        let text = clean(value);
        while (prefix.test(text)) text = text.replace(prefix, '').trim();
        return unresolved.test(text) ? '' : text;
      }).filter(Boolean))];
      const aliases = new Map([
        ['xiaohongshu', '小红书'], ['xhs', '小红书'], ['rednote', '小红书'],
        ['wechat', '微信'], ['wechat_channels', '视频号'], ['wechat_channel', '视频号'],
        ['weixin_channels', '视频号'], ['weixin_video', '视频号'], ['video_account', '视频号'], ['视频号', '视频号'], ['微信视频号', '视频号'],
        ['douyin', '抖音'], ['bilibili', '哔哩哔哩'], ['b站', '哔哩哔哩'],
        ['kuaishou', '快手'], ['weibo', '微博'], ['zhihu', '知乎'], ['toutiao', '今日头条']
      ]);
      const day = (...values) => {
        for (const value of values) {
          const date = clean(value).match(/^(\d{4}-\d{2}-\d{2})(?=$|[Tt\s])/u)?.[1];
          if (!date || date.startsWith('0000-')) continue;
          const utc = new Date(date + 'T00:00:00Z');
          if (Number.isFinite(utc.getTime()) && utc.toISOString().slice(0, 10) === date) return date;
        }
        return '';
      };
      const postId = (...values) => {
        for (const value of values) {
          if (clean(value)) return clean(value);
          if (Number.isSafeInteger(value)) return String(value);
        }
        return '';
      };
      const postsByPlatform = new Map();
      for (const m of array(info?.metrics)) {
        if (!m || !clean(m.label) || !(typeof m.value === 'number' ? Number.isFinite(m.value) : clean(m.value))) continue;
        const rawPlatform = clean(m.platform);
        const platform = aliases.get(rawPlatform.toLowerCase().replace(/[\s-]+/gu, '_')) || rawPlatform || '未标注平台';
        const parts = m.label.split(/\s*[·｜|]\s*/u);
        let taggedPost = '', taggedCapture = '', taggedWindow = '';
        const label = parts.filter((part, index) => {
          if (!index) return true;
          const suffix = part.trim();
          let match = suffix.match(/^(?:发布(?:记录|编号|ID)?|帖(?:子)?(?:编号|ID)?)(?:\s*[:：#]\s*|\s+|$)(.*)$/iu);
          if (match) {
            const id = match[1].trim();
            if (/^[\w-]+$/u.test(id) && !/^(?:[-_]+|unknown|null|undefined|n-a)$/iu.test(id) && !day(id)) taggedPost ||= id;
            return false;
          }
          match = suffix.match(/^采集(?:日期|时间|日)?(?:\s*[:：]\s*|\s+|$)(.*)$/u);
          if (match) { taggedCapture ||= day(match[1]); return false; }
          match = suffix.match(/^(?:归因(?:窗口|期)|窗口)(?:\s*[:：]\s*|\s+|$)(.*)$/u);
          if (match) { taggedWindow ||= match[1].trim(); return false; }
          return true;
        }).join(' · ').trim();
        if (!label) continue;
        const id = postId(m.publication_id, m.publicationId, m.publication_record_id, m.publish_id, m.publishId, taggedPost, m.post_id, m.postId);
        const published = day(m.published_at, m.publishedAt, m.publish_at, m.published_date, m.publish_date, m.publication_date, m.publicationDate);
        const captured = day(m.collected_at, m.collectedAt, m.captured_at, m.capturedAt, m.collection_date, m.collected_date, m.capture_date, taggedCapture);
        const windowDays = m.attribution_window_days ?? m.attributionWindowDays;
        const explicitWindow = first(m.attribution_window, m.attributionWindow, taggedWindow);
        const windowText = (/^\d+(?:\.\d+)?$/u.test(str(windowDays)) ? `${windowDays} 天` : '') || explicitWindow;
        const note = [captured && `采集 ${captured}`, windowText && `归因窗口 ${windowText}`].filter(Boolean).join(' · ');
        let value = str(m.value).trim();
        const unit = first(m.value_unit, m.valueUnit, m.metric_unit, m.unit).toLowerCase();
        if (/^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:e[+-]?\d+)?$/iu.test(value) && Number.isFinite(Number(value))) {
          if (/^(?:%|％|percent|percentage|百分比)$/u.test(unit)) value += '%';
          else if (/^(?:fraction|ratio|小数比例)$/u.test(unit) && /率|占比|\brate\b|\bpercentage\b/iu.test(label)) {
            value = new Intl.NumberFormat('zh-CN', {style: 'percent', maximumSignificantDigits: 15, useGrouping: false}).format(Number(value));
          }
        }
        if (!postsByPlatform.has(platform)) postsByPlatform.set(platform, new Map());
        const posts = postsByPlatform.get(platform);
        const key = id ? JSON.stringify(['id', id]) : JSON.stringify(['unknown']);
        if (!posts.has(key)) posts.set(key, {id, published, rows: []});
        const post = posts.get(key);
        if (!post.published) post.published = published;
        post.rows.push({label, value, note});
      }
      if (!highlights.length && !postsByPlatform.size) return null;
      const section = el('section', null, 'reading-info');
      section.setAttribute('aria-label', '作品阅读信息');
      if (highlights.length) {
        const list = el('ul', null, 'reading-highlights');
        list.setAttribute('aria-label', '传播要素');
        for (const text of highlights) list.append(el('li', text));
        section.append(list);
      }
      const priority = label => /^(?:播放量|观看量|阅读量|曝光量|浏览量|点赞量|点赞数|互动量|互动率|完播率)(?=$|\s|[（(·：:])/u.test(label);
      const seq = readingMetadata.noteSequence = (readingMetadata.noteSequence || 0) + 1;
      let groupIndex = 0;
      for (const [platform, posts] of postsByPlatform) {
        let postIndex = 0;
        for (const post of posts.values()) {
          const index = ++groupIndex;
          const initial = platform + (posts.size > 1 ? (post.id ? ` · 帖子 ${String(++postIndex).padStart(2, '0')}` : ' · 未标注发布记录') : '');
          const title = initial + (post.published ? ` · ${post.published}` : '');
          const block = group('reading-post-metrics', el('h3', title, 'reading-post-title'));
          const notes = [...new Set(post.rows.map(row => row.note))];
          const mixed = notes.length > 1;
          const knownNotes = notes.filter(Boolean);
          const noteRefs = new Map();
          if (mixed && knownNotes.length) {
            const legend = el('details', null, 'reading-metric-notes');
            legend.append(el('summary', '采集与归因说明'));
            const ol = el('ol');
            for (const [i, text] of knownNotes.entries()) {
              const li = el('li', text);
              li.id = `reading-metric-note-${seq}-${index}-${i + 1}`;
              noteRefs.set(text, {id: li.id, number: i + 1});
              ol.append(li);
            }
            legend.append(ol);
            block.append(legend);
          } else if (knownNotes.length) {
            block.append(el('p', knownNotes[0], 'reading-metric-note'));
          }
          const makeGrid = rows => {
            const dl = el('dl', null, 'reading-metrics reading-metrics-compact');
            for (const row of rows) {
              const dt = el('dt', row.label);
              const dd = el('dd', row.value);
              const ref = noteRefs.get(row.note);
              if (ref) {
                const marker = el('sup', ` ${ref.number}`, 'reading-metric-marker');
                marker.setAttribute('aria-hidden', 'true');
                dt.append(marker);
                dd.setAttribute('aria-describedby', ref.id);
              }
              dl.append(group('reading-metric', dt, dd));
            }
            return dl;
          };
          const rows = [...post.rows.filter(row => priority(row.label)), ...post.rows.filter(row => !priority(row.label))];
          block.append(makeGrid(rows.slice(0, 4)));
          if (rows.length > 4) {
            const more = el('details', null, 'reading-metrics-more');
            more.append(el('summary', `全部数据（另 ${rows.length - 4} 项）`), makeGrid(rows.slice(4)));
            block.append(more);
          }
          section.append(block);
        }
      }
      return section;
    }
    function readable(item) {
      const source = Array.isArray(item.readable_blocks) ? item.readable_blocks : array(item.blocks);
      return source.filter(b => b && typeof b.text === 'string' && b.text.trim()).map(b => ({
        text: b.text, start: Number(b.start)
      }));
    }
    function offsets(block, ref) {
      if (!ref?.line || !ref.text || !Number.isSafeInteger(block.start) || block.start < 1) return [];
      const text = block.text;
      let line = block.start, lo = 0;
      if (ref.line < line) return [];
      while (line < ref.line) {
        const next = text.indexOf('\n', lo);
        if (next < 0) return [];
        lo = next + 1;
        ++line;
      }
      const nl = text.indexOf('\n', lo);
      const hi = nl < 0 ? text.length : nl;
      const matches = [];
      for (let i = text.indexOf(ref.text, lo); i >= 0 && i < hi; i = text.indexOf(ref.text, i + 1)) matches.push(i);
      if (matches.length > 1 && ref.context && ref.context !== ref.text) {
        const narrowed = matches.filter(i => {
          for (let p = text.indexOf(ref.context); p >= 0 && p <= i; p = text.indexOf(ref.context, p + 1)) {
            if (i + ref.text.length <= p + ref.context.length) return true;
          }
          return false;
        });
        if (narrowed.length) return narrowed;
      }
      return matches;
    }
    function paragraph(block, intervals) {
      const p = el('p', null, 'body');
      p.style.whiteSpace = 'pre-wrap';
      const edges = new Map();
      const edge = n => {
        if (!edges.has(n)) edges.set(n, {all: 0, active: 0});
        return edges.get(n);
      };
      edge(0);
      edge(block.text.length);
      for (const r of intervals) {
        edge(r.start).all++;
        edge(r.end).all--;
        if (r.active) { edge(r.start).active++; edge(r.end).active--; }
      }
      const points = Array.from(edges.keys()).sort((a, b) => a - b);
      let all = 0, active = 0, target = null;
      for (let j = 0; j + 1 < points.length; j++) {
        const at = points[j], delta = edges.get(at);
        all += delta.all;
        active += delta.active;
        const text = block.text.slice(at, points[j + 1]);
        if (all) {
          const mark = el('mark', text, active ? 'current quote-target' : '');
          p.append(mark);
          if (active && !target) target = mark;
        } else p.append(document.createTextNode(text));
      }
      return {node: p, target};
    }
    function displayWork(item, page, jump = false, {background = false, quote = null} = {}) {
      const id = str(item.source_id);
      const refs = refsByWork.get(id) || [];
      const blocks = quote?.blocks || readable(item);
      const targetRef = quote?.ref || (page.ref?.source === id ? page.ref : null);
      const summary = workById.get(id);
      const title = summary?.title || item.title || targetRef?.title || '未命名作品';
      const info = item.reading_info ?? summary?.reading_info;
      const key = 'work:' + JSON.stringify([id, item.hash, title, info, refs, targetRef, quote?.signature]);
      paintReading(page, key, background, () => {
        const targets = targetRef ? blocks.map(b => offsets(b, targetRef)) : [];
        const matches = targets.reduce((n, a) => n + a.length, 0);
        const actions = quote ? null : group('actions',
          button('用于写作', () => writeFrom('work', id), null, 'work-write'),
          button('校订正文', () => { if (!deferredReading) edit(item); }, null, 'work-edit'),
          button('手动补收金句', () => { if (!deferredReading) edit(item, true); }, 'primary', 'work-quote'),
          button('从可用正文移除', () => {
            if (deferredReading || !confirm('从两端的可用正文中移除《' + item.title + '》？原件会保留。')) return;
            return write('works.remove', {source_id: item.source_id, expected_hash: item.hash}, () =>
              refreshAfterWrite({...state, page: null, card: null}, '正文已移除。', null, false));
          }, 'danger', 'work-remove'));
        const article = el('article', null, 'reading compact-reading'), nodes = new Map();
        const titleNode = el(quote ? 'h3' : 'h2', title, 'reading-title');
        const metadata = readingMetadata(info);
        let target = null;
        blocks.forEach((block, i) => {
          const ranges = [];
          for (const ref of refs) {
            for (const start of offsets(block, ref)) ranges.push({start, end: start + ref.text.length});
          }
          if (matches === 1) {
            for (const start of targets[i]) ranges.push({start, end: start + targetRef.text.length, active: true});
          }
          const part = paragraph(block, ranges);
          nodes.set(part.node, block);
          article.append(part.node);
          target ||= part.target;
        });
        if (!blocks.length) article.append(hint('暂无可显示的正文段落。'));
        setDetail(key, [
          ...(quote ? [quote.heading] : []), titleNode, ...(metadata ? [metadata] : []),
          ...(quote ? quote.toolbar : [actions]),
          ...(targetRef && matches !== 1 ? [hint(matches ? '有多处相同措辞，无法唯一定位。'
            : '当前正文无法定位该句，下面是完整可读正文。')] : []),
          article, ...(quote?.tail || [])
        ]);
        reader = {item, article, nodes, targetKey: JSON.stringify(targetRef)};
        if (target && jump) requestAnimationFrame(() => {
          if (state.page === page && target.isConnected && !holdsReadingSelection()) target.scrollIntoView({block: 'center'});
        });
      });
    }
    function fetchWork(id) {
      const at = globalRevision;
      const existing = workLoads.get(id);
      if (existing && Object.is(existing.at, at)) return existing.promise;
      const entry = {at};
      entry.promise = api('works.get', {source_id: id})
        .then(({item, revision}) => ({item, revision, at}))
        .finally(() => { if (workLoads.get(id) === entry) workLoads.delete(id); });
      workLoads.set(id, entry);
      return entry.promise;
    }
    async function renderPage(load, restorePos) {
      if (draft) return;
      const page = state.page;
      detail.hidden = !page && state.mode !== 'map';
      if (!page) {
        if (state.mode === 'map') mapPage();
        else setDetail('browse', []);
        return;
      }
      if (page.kind === 'quotes') return quotePage(page, load, restorePos);
      const record = cachedWork(page.id);
      if (record?.item) {
        displayWork(record.item, page, load && !restorePos);
        return;
      }
      if (!load) return;
      const token = epoch;
      const valid = () => token === epoch && state.page === page && !draft;
      if (!record) setDetail('loading:' + page.id, [hint('正在读取完整正文…')]);
      try {
        const latest = await loadWork(page.id);
        if (!valid()) return;
        displayWork(latest.item, page, !restorePos);
        restore(restorePos);
      } catch (e) {
        if (!valid()) return;
        showWorkError(page, e, false, restorePos);
      }
    }

    function labeled(tag, label, value = '') {
      const input = el(tag);
      input.setAttribute('aria-label', label);
      input.placeholder = label;
      input.value = value;
      return input;
    }
    function edit(item, isQuote = false) {
      if (!mayLeave()) return;
      if (!item) {
        trail.push({state: {...state}, pos: position()});
        state = {...state, mode: 'works', page: null};
        syncHash();
      }
      ++epoch;
      const form = {id: item ? str(item.source_id) : null, hash: item?.hash, dirty: false, conflict: null};
      draft = form;
      renderShell();
      detail.hidden = false;
      const formNode = el('form');
      const title = isQuote ? null : labeled('input', '作品标题', item?.title || '');
      const text = labeled('textarea', isQuote ? '金句原文' : '作品正文', isQuote ? '' : item?.text || '');
      const restoreRemoved = el('input');
      restoreRemoved.type = 'checkbox';
      const label = el('label');
      label.append(restoreRemoved, ' 恢复此前亲自移除的这句');
      const save = el('button', isQuote ? '收进金句' : '保存正文', 'primary');
      save.type = 'submit';
      const cancel = button('取消', () => {
        if (!item) return back();
        if (!mayLeave()) return;
        draft = null;
        ++epoch;
        viewKey = '';
        message();
        renderShell();
        return renderPage(true);
      }, 'text-button');
      const choice = el('select');
      choice.setAttribute('aria-label', '选择对应出处');
      choice.hidden = true;
      if (title) formNode.append(title);
      formNode.append(text);
      if (isQuote) formNode.append(choice, label);
      formNode.append(group('actions', save, cancel));
      formNode.oninput = () => {
        form.dirty = true;
        if (choice.hidden || document.activeElement === text) {
          choice.hidden = true;
          choice.replaceChildren();
        }
      };
      formNode.onsubmit = event => {
        event.preventDefault();
        run(async () => {
          if (draft !== form || writing) return;
          if (form.conflict) { message('请先处理版本冲突。', true); return; }
          if (isQuote) {
            const value = text.value.trim();
            if (value.length < 2 || value.length > 4000) throw new Error('请输入 2 至 4000 字的连续原话。');
            const hits = new Map();
            for (const b of readable(item)) {
              if (!Number.isSafeInteger(b.start) || b.start < 1) continue;
              for (let i = b.text.indexOf(value); i >= 0; i = b.text.indexOf(value, i + 1)) {
                const line = b.start + b.text.slice(0, i).split('\n').length - 1;
                const snippet = b.text.slice(Math.max(0, i - 24), Math.min(b.text.length, i + value.length + 24));
                if (!hits.has(line)) hits.set(line, snippet.replace(/\s+/g, ' '));
              }
            }
            if (!hits.size) throw new Error('未找到这段连续原话，请核对措辞。');
            if (hits.size > 1 && (choice.hidden || !hits.has(Number(choice.value)))) {
              choice.replaceChildren(new Option('同句多次出现，请选择对应片段', ''),
                ...Array.from(hits, ([line, snippet], i) => new Option(`出处 ${i + 1} · ${snippet}`, String(line))));
              choice.hidden = false;
              choice.focus();
              return;
            }
            await write('quotes.add', {source_id: item.source_id, expected_hash: form.hash, text: value,
              start_line: hits.size === 1 ? hits.keys().next().value : Number(choice.value),
              restore: restoreRemoved.checked}, r => openAddedQuote(r, '已收录。'));
          } else {
            if (!title.value.trim() || !text.value.trim()) throw new Error('请填写标题和正文。');
            await write('works.save', {source_id: item?.source_id, expected_hash: form.hash,
              title: title.value, text: text.value}, r =>
              refreshAfterWrite({...state, mode: 'works', page: {kind: 'works', id: str(r.item.source_id)}},
                '正文已保存。', r.item, false));
          }
        });
      };
      const sample = isQuote ? readable(item).map(b => {
        const p = el('p', b.text, 'body');
        p.style.whiteSpace = 'pre-wrap';
        return p;
      }) : [];
      setDetail('form:' + epoch, [
        el('h2', isQuote ? '从正文补收金句' : item ? '校订正文' : '新增正文'),
        hint(isQuote ? '复制下方正文中的连续原话；保留外部引文的原作者署名。' : '保留原有语气、重复和叙述顺序，只改能确认的问题。'),
        formNode, ...sample
      ]);
      (title || text).focus();
    }
    function readSelection() {
      pending = null;
      clip.hidden = true;
      const selection = window.getSelection();
      if (deferredReading && !holdsReadingSelection()) {
        const update = deferredReading;
        deferredReading = null;
        if (update.page === state.page && !draft) update.apply();
      }
      if (!reader || draft || deferredReading || state.page?.kind === 'quotes' || !selection?.rangeCount || selection.isCollapsed) return;
      const range = selection.getRangeAt(0);
      const node = range.startContainer;
      const p = (node.nodeType === Node.ELEMENT_NODE ? node : node.parentElement)?.closest('.body');
      const block = reader.nodes.get(p);
      if (!block || !p.contains(range.endContainer) || !Number.isSafeInteger(block.start) || block.start < 1) return;
      const raw = range.toString(), text = raw.trim();
      if (text.length < 2 || text.length > 4000) return;
      const prefix = document.createRange();
      prefix.selectNodeContents(p);
      prefix.setEnd(range.startContainer, range.startOffset);
      const pos = prefix.toString().length + raw.length - raw.trimStart().length;
      if (block.text.slice(pos, pos + text.length) !== text) return;
      pending = {source_id: reader.item.source_id, expected_hash: reader.item.hash, text,
        start_line: block.start + block.text.slice(0, pos).split('\n').length - 1};
      clip.hidden = false;
    }

    async function checkDraft(form, valid, revision) {
      try {
        const latest = await fetchWork(form.id);
        if (!valid()) return;
        form.checked = revision || latest.revision;
        if (latest.item.hash !== form.hash && form.conflict !== 'changed') {
          form.conflict = 'changed';
          message();
        }
      } catch (e) {
        if (!missing(e)) throw e;
        if (!valid()) return;
        form.checked = revision;
        if (form.conflict !== 'removed') {
          form.conflict = 'removed';
          message();
        }
      }
    }
    const sameRevision = (a, b) => !!a && !!b && Object.is(a.global, b.global) && Object.is(a.detail, b.detail);
    async function refreshChanges(forceCatalog = false) {
      if (document.hidden || polling || busy || writing) return;
      polling = true;
      const token = epoch, m = mutation, page = state.page, form = draft;
      const valid = () => !document.hidden && !busy && !writing && token === epoch && m === mutation && form === draft;
      try {
        const watch = form?.id ? 'works:' + form.id : page ? page.kind + ':' + page.id : '';
        const {revision} = await api('library.revision', {watch});
        if (!valid() || !revision) return;
        const quoteChanged = !form && page?.kind === 'quotes' &&
          (quoteCheck?.id !== page.id || !sameRevision(quoteCheck.revision, revision));
        if (forceCatalog || quoteChanged || !catalog || !Object.is(globalRevision, revision.global)) {
          const data = await api('library.catalog');
          if (!valid()) return;
          installCatalog(data);
          if (page?.kind === 'quotes' && Object.is(globalRevision, revision.global)) quoteCheck = {id: page.id, revision};
          preserve(() => {
            renderShell();
            if (!form && !page) renderPage(false);
          });
        }
        if (form?.id) {
          if (!sameRevision(form.checked, revision)) await checkDraft(form, valid, revision);
          return;
        }
        if (form || !page) return;
        if (page.kind === 'quotes') {
          if (quoteById.has(page.id) && quoteWatch?.page === page) {
            const watched = await Promise.all(quoteWatch.sources.map(async id => {
              try { return [id, (await api('library.revision', {watch: 'works:' + id})).revision]; }
              catch { return [id, null]; }
            }));
            if (!valid()) return;
            for (const [id, rev] of watched) checkWorkWatch(id, rev);
          }
          if (valid()) await quotePage(page);
          return;
        }
        checkWorkWatch(page.id, revision);
        try {
          const latest = await loadWork(page.id);
          if (valid()) displayWork(latest.item, page, !reader && !!page.ref, {background: true});
        } catch (e) {
          if (valid() && missing(e)) showWorkError(page, e, true);
        }
      } catch {
        // 后台失败时保留当前页面与草稿，下次重试。
      } finally { polling = false; }
    }

    $('home').onclick = () => run(home);
    $('back').onclick = () => run(back);
    for (const tab of tabs) $(tab).onclick = () => run(() => switchTab(tab));
    $('new').onclick = () => run(() => {
      if (state.mode === 'works') return edit(null);
      if (!mayLeave()) return;
      const result = switchTab('works');
      message('请选择一份作品，选中原话或点击“手动补收金句”。');
      return result;
    });
    search.oninput = () => {
      if (state.page || draft || state.q === search.value) return;
      state.q = search.value;
      state.card = null;
      renderList();
      if (state.mode === 'map' && state.domain !== null && catalog) mapPage();
    };
    more.hidden = true;
    document.addEventListener('selectionchange', readSelection);
    clip.onpointerdown = event => event.preventDefault();
    clip.onclick = () => run(() => {
      const selection = pending;
      if (!selection || draft || !reader || selection.source_id !== reader.item.source_id) return;
      return write('quotes.add', selection, r => openAddedQuote(r, '已收录。'));
    });
    const onFocus = () => {
      clearTimeout(focusTimer);
      focusTimer = setTimeout(() => refreshChanges(true), 120);
    };
    window.addEventListener('focus', onFocus);
    document.addEventListener('visibilitychange', () => { if (!document.hidden) onFocus(); });
    window.addEventListener('hashchange', event => onHash(window, event));
    host?.addEventListener('hashchange', event => onHash(host, event));
    setInterval(refreshChanges, 5000);

    resetReader();
    search.value = state.q;
    syncHash();
    renderShell();
    renderPage(false);
    run(async () => {
      try {
        const data = await api('library.catalog');
        if (catalog) return;
        installCatalog(data);
        preserve(() => { renderShell(); renderPage(false); });
      } catch (e) {
        if (!catalog && !state.page && !draft && state.mode === 'map') {
          setDetail('catalog-error', [hint('目录读取失败，将自动重试。'),
            button('重试', async () => {
              installCatalog(await api('library.catalog'));
              preserve(() => { renderShell(); renderPage(false); });
            }, null, 'retry-catalog')]);
        }
        throw e;
      }
    });
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init, {once: true});
  else init();
})();
