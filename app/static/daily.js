const day = document.querySelector('#day');
const sort = document.querySelector('#sort');
const margin = document.querySelector('#margin');
const games = document.querySelector('#games');
const status = document.querySelector('#status');
const percent = new Intl.NumberFormat('fr-FR', {style: 'percent', maximumFractionDigits: 1});
const date = new Intl.DateTimeFormat('fr-FR', {weekday: 'short', day: 'numeric', month: 'long', timeZone: 'UTC'});
const hour = new Intl.DateTimeFormat('fr-FR', {weekday: 'short', hour: '2-digit', minute: '2-digit', timeZone: 'Europe/Paris'});
let payload;
let lastToday;
if (['0', '5', '10'].includes(localStorage.getItem('nba-total-margin'))) {
  margin.value = localStorage.getItem('nba-total-margin');
}
const nbaDay = new Intl.DateTimeFormat('en-CA', {
  timeZone: 'America/New_York', year: 'numeric', month: '2-digit', day: '2-digit'
});

function node(tag, text, className) {
  const element = document.createElement(tag);
  element.textContent = text;
  if (className) element.className = className;
  return element;
}

function pick(label, selection, probability, detail) {
  const element = node('div', '', 'pick');
  element.append(node('span', label, 'metric'), node('strong', selection),
    node('span', Number.isFinite(probability) ? percent.format(probability) : '—', 'probability'),
    node('small', detail));
  return element;
}

function resultBadge(outcome) {
  return node('small', outcome, 'pick-result ' + (
    outcome === 'Passé' ? 'won' : outcome === 'Raté' ? 'lost' : 'pending'
  ));
}

function totalOutcome(selection, score) {
  if (!score) return 'Résultat en attente';
  if (!selection || !Number.isFinite(selection.line)) return 'Pick indisponible';
  const difference = score.home + score.away - selection.line;
  if (difference === 0) return 'Égalité sur la ligne';
  return (difference > 0) === (selection.direction === 'Over') ? 'Passé' : 'Raté';
}

function render() {
  if (!payload) return;
  const history = day.value === payload.yesterday;
  const totalPick = game => {
    const reference = game.total?.reference;
    return game.total?.references?.[margin.value] ??
      (reference && Number(margin.value) === (reference.margin_points ?? 0) ? reference : null);
  };
  const metric = sort.value === 'total' ? game => totalPick(game)?.probability ?? -1 : game => game.pick_probability;
  const backtest = payload.backtest || {};
  const totalStats = backtest.totals_by_margin?.[margin.value] ??
    ((backtest.total?.margin_points ?? 0) === Number(margin.value) ? backtest.total : null);
  for (const [id, stats] of [['winner', backtest.winner], ['total', totalStats]]) {
    document.querySelector('#' + id + '-rate').textContent = stats ? percent.format(stats.accuracy) : '—';
    const detail = stats ? `${stats.wins} picks corrects sur ${stats.count}` : '';
    document.querySelector('#' + id + '-count').textContent = detail && id === 'total' ? `${detail} · marge ${margin.value} pts` : detail;
  }
  const now = Date.now();
  const slate = payload.games.filter(game => game.date === day.value).map(game =>
    !game.status && Date.parse(game.start_time) - now > 24 * 3600000
      ? {...game, pick: null, outside_window: true} : game);
  const ranked = slate.filter(game => game.pick && game.total).sort((a, b) => metric(b) - metric(a));
  status.textContent = `${slate.length} match${slate.length === 1 ? '' : 's'} · horaires de Paris`;
  const generated = history ? NaN : Date.parse(payload.generated_at);
  if (Number.isFinite(generated)) {
    status.textContent += ` · picks recalculés ${hour.format(generated)}`;
    if (Date.now() - generated > 5 * 60000) status.textContent += ' · actualisation en retard';
  }
  games.replaceChildren();
  for (const game of [...ranked, ...slate.filter(game => !game.pick || !game.total)]) {
    const card = node('article', '');
    const start = new Date(game.start_time || '');
    const time = Number.isFinite(start.getTime()) ? hour.format(start) : 'Horaire à confirmer';
    card.append(node('div', time + (game.status ? ' · ' + game.status : ''), 'match-meta'),
      node('h2', game.away_team + ' – ' + game.home_team));
    const score = game.final_score;
    if (history && score) {
      card.append(node('p', `Score final · ${score.away}–${score.home} · Total ${score.away + score.home} pts`, 'match-meta'));
    }
    if (game.pick && game.total) {
      const picks = node('div', '', 'picks');
      const total = game.total;
      const winnerDetail = game.no_bet_reason || (game.moneyline_quote ? `Cote ${game.moneyline_quote.price}` : 'Estimation pré-match');
      const quote = total.market_signal;
      const reference = totalPick(game);
      const line = `Ligne du modèle · marge ${margin.value} pts · projection ${total.projection} pts`;
      const winnerCard = pick('Vainqueur', game.pick, game.pick_probability, winnerDetail);
      const totalCard = pick('Over/under', reference?.selection ?? (history ? 'Pick indisponible' : 'En attente de recalcul'),
        reference?.probability, line);
      if (history) {
        const winner = score && (score.home > score.away ? game.home_team : game.away_team);
        winnerCard.append(resultBadge(winner ? (winner === game.pick ? 'Passé' : 'Raté') : 'Résultat en attente'));
        totalCard.append(resultBadge(totalOutcome(reference, score)));
      }
      if (quote) {
        const bookDetail = `${quote.book} · cote ${quote.price}`;
        const observation = quote.margin_met === false ? ' · observation' : '';
        const result = history ? ` · ${totalOutcome(quote, score)}` : '';
        totalCard.append(node('small',
          `${quote.selection} chez ${bookDetail} · ${percent.format(quote.probability)}${observation}${result}`));
      }
      picks.append(winnerCard, totalCard);
      card.append(picks);
    } else {
      const detail = history ? 'Aucun pick enregistré avant le match.'
        : game.status ? 'Prévision pré-match indisponible.'
        : game.outside_window ? 'Picks disponibles 24 h avant le match.' : 'Prévision en cours.';
      card.append(node('small', detail));
    }
    games.append(card);
  }
  if (!slate.length) games.append(node('p', 'Aucun match programmé pour cette journée.'));
}

async function refresh() {
  try {
    const data = await getJson('/api/picks');
    payload = Array.isArray(data.games) && Array.isArray(data.dates) ? data : await legacyBoard(data);
    if (!payload.backtest?.totals_by_margin) {
      const snapshot = await getJson('/static/daily-backtest.json').catch(() => null);
      if (snapshot?.totals_by_margin) payload.backtest = snapshot;
    }
    const previous = day.value;
    day.replaceChildren(...payload.dates.map(value => {
      const dayLabel = date.format(new Date(value + 'T00:00:00Z'));
      const option = node('option', value === payload.yesterday ? `Historique · veille (${dayLabel})` : dayLabel);
      option.value = value;
      return option;
    }));
    day.value = previous && previous !== lastToday && payload.dates.includes(previous) ? previous : payload.today;
    lastToday = payload.today;
    render();
  } catch {
    status.textContent = 'Données indisponibles. Nouvelle tentative dans une minute.';
  }
}

async function getJson(path) {
  const response = await fetch(path, {cache: 'no-store'});
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return response.json();
}

async function legacyBoard(data) {
  if (!Array.isArray(data.picks)) throw new Error('Format de prévisions inconnu');
  const [calendar, backtest] = await Promise.all([
    getJson('/api/calendar'),
    getJson('/static/daily-backtest.json').catch(() => ({}))
  ]);
  const now = new Date();
  const parts = Object.fromEntries(nbaDay.formatToParts(now).map(part => [part.type, part.value]));
  const midnight = Date.UTC(parts.year, Number(parts.month) - 1, parts.day);
  const dates = Array.from({length: 8}, (_, index) => new Date(midnight + index * 86400000).toISOString().slice(0, 10));
  const picks = new Map(data.picks.filter(pick => pick.model === 'daily_strategy').map(pick => [pick.game_id, pick]));
  const games = calendar.games.filter(game => dates.includes(game.date)).map(game => {
    const start = Date.parse(game.start_time);
    const status = game.home_points != null ? 'Terminé' : start <= now ? 'Coup d’envoi passé' : null;
    const outside_window = !status && start - now > 24 * 3600000;
    const prediction = outside_window ? undefined : picks.get(game.game_id);
    const total = prediction?.total;
    const fresh = quote => {
      const age = now - Date.parse(quote?.captured_at);
      return age >= 0 && age <= 4 * 3600000;
    };
    return {
      ...prediction, ...game, status, outside_window,
      moneyline_quote: fresh(prediction?.moneyline_quote) ? prediction.moneyline_quote : null,
      total: total?.market_signal && !fresh(total.market_signal) && total.reference
        ? {...total, market_signal: null, display_pick: total.reference.selection,
           pick_probability: total.reference.probability}
        : total
    };
  });
  return {today: dates[0], dates, games, backtest, generated_at: data.generated_at};
}

day.addEventListener('change', render);
sort.addEventListener('change', render);
margin.addEventListener('change', () => {
  localStorage.setItem('nba-total-margin', margin.value);
  render();
});
refresh();
setInterval(refresh, 60000);
