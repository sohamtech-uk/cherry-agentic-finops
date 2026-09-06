# Analysis loading experience

The upload analysis endpoint currently returns one completed response rather than streaming stage-by-stage progress. The waiting UI therefore must not display fabricated percentages or mark backend stages complete before the server says so.

The **Evidence Control Room** keeps the wait engaging by showing:

- evidence already selected in the browser or recognised in the active Fund Manager case;
- the governed control architecture as an explanatory sequence, explicitly labelled as sequence rather than progress;
- elapsed request time;
- rotating product control principles that explain the design boundary to judges;
- explicit zero financial-write and payment authority boundaries; and
- responsive and reduced-motion behaviour.

The existing global `loading(true|false)` API remains unchanged. `fund_manager_completion.js` decorates that function after page load so current callers in `app.js`, `fund_manager.js`, `clear_dialog.js`, and other browser scripts do not need to change.

When backend streaming is introduced later, real stage events can replace the explanatory sequence. Until then, the UI should continue to prefer truthful waiting state over simulated completion percentages.
