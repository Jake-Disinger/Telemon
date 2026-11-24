/* Display configuration — edit freely. Model keys must match pipeline/config.json. */
window.TELE_CONFIG = {
  siteLabel: "Teleconnection Monitor",   // shown in blue next to "Updated -->" (like weathermodels.com)
  dataPath: "data/",                     // where manifest.json / runs/ / analysis.json live
  refreshMinutes: 5,                     // poll for new runs (page follows "Latest" automatically)
  obsDaysBefore: 8,                      // days of observed index shown left of the init time
  daysAfter: 18,                         // forecast days shown on the multi-model chart
  sameCycleHours: 24,                    // all-model view: use a model's run if within this many hours of the cycle

  // Legend order follows weathermodels.com: row 1 then row 2 (three per row).
  models: {
    hres: { label: "ECMWF HRES",     short: "ECMWF HRES", color: "#1a6fef", symbol: "square", filled: true,  kind: "det" },
    gfs:  { label: "NOAA GFS",       short: "NOAA GFS",   color: "#f03c3c", symbol: "circle", filled: true,  kind: "det" },
    aifs: { label: "ECMWF AIFS",     short: "ECMWF AIFS", color: "#8a72de", symbol: "circle", filled: false, kind: "det" },
    eps:  { label: "ECMWF EPS MEAN", short: "ECMWF EPS",  color: "#1a6fef", symbol: "square", filled: false, kind: "ens" },
    gefs: { label: "NOAA GEFS",      short: "NOAA GEFS",  color: "#f03c3c", symbol: "circle", filled: false, kind: "ens" },
    geps: { label: "CANADA GEPS",    short: "CANADA GEPS",color: "#1d9a2b", symbol: "circle", filled: false, kind: "ens" }
  },

  indices: {
    nao: { name: "North Atlantic Oscillation", abbr: "NAO" },
    ao:  { name: "Arctic Oscillation",         abbr: "AO"  },
    pna: { name: "Pacific North American Pattern", abbr: "PNA" },
    epo: { name: "East Pacific Oscillation",   abbr: "EPO" },
    aam: { name: "Atmospheric Angular Momentum", abbr: "AAM", rawUnit: "x10^24 kg m² s⁻¹" },
    mjo: { name: "Madden-Julian Oscillation",  abbr: "MJO" }
  },

  // ---- Bering Sea Rule tab ----------------------------------------------------------
  bsr: {
    lagDays: 18,                       // default lag (adjustable on the page, 10-25 days)
    // where the US outline is placed, as on the classic overlay charts: a flat US map whose
    // center (39N, 96W) lands at lat/lon (deg E), `scale` x the chart's scale there, rotated
    // `rot` degrees counter-clockwise. Fitted to a classic Bering Sea Rule chart.
    overlay: { lat: 46.25, lon: 172.97, scale: 1.22, rot: 10.3 },
    mapBounds: { latN: 70, latS: 18, lonW: 125, lonE: 240 },
    // OPC Pacific charts. If an image doesn't load, fix its URL here. `cal` is the chart's
    // pixel calibration: click "Calibrate" on the page, then paste the result here so
    // everyone gets the overlay without calibrating.
    opc: [
      { key: "sfc00", title: "Surface analysis",      url: "https://ocean.weather.gov/shtml/P_full_00hrsfc.gif", lead: 0,  cal: null },
      { key: "sfc24", title: "24-hour surface forecast", url: "https://ocean.weather.gov/shtml/P_24hrsfc.gif", lead: 24, cal: null },
      { key: "sfc48", title: "48-hour surface forecast", url: "https://ocean.weather.gov/shtml/P_48hrsfc.gif", lead: 48, cal: null },
      { key: "sfc72", title: "72-hour surface forecast", url: "https://ocean.weather.gov/shtml/P_72hrsfc.gif", lead: 72, cal: null },
      { key: "sfc96", title: "96-hour surface forecast", url: "https://ocean.weather.gov/shtml/P_96hrsfc.gif", lead: 96, cal: null }
    ]
  },

  // ---- Typhoon Rule tab ------------------------------------------------------------
  typhoon: {
    lagDays: [6, 10],                  // eastern-US trough window after recurvature near Japan
    mapBounds: { latN: 55, latS: 0, lonW: 100, lonE: 190 },
    japanBox: { lat: [24, 46], lon: [122, 150] },
    daysShown: 45
  },

  // "Outlooks" tab: any image URLs (CPC products shown by default). Edit/add as needed.
  outlooks: [
    { group: "CPC 6-10 Day", items: [
      { title: "6-10 Day Temperature",   img: "https://www.cpc.ncep.noaa.gov/products/predictions/610day/610temp.new.gif", link: "https://www.cpc.ncep.noaa.gov/products/predictions/610day/" },
      { title: "6-10 Day Precipitation", img: "https://www.cpc.ncep.noaa.gov/products/predictions/610day/610prcp.new.gif", link: "https://www.cpc.ncep.noaa.gov/products/predictions/610day/" } ] },
    { group: "CPC 8-14 Day", items: [
      { title: "8-14 Day Temperature",   img: "https://www.cpc.ncep.noaa.gov/products/predictions/814day/814temp.new.gif", link: "https://www.cpc.ncep.noaa.gov/products/predictions/814day/" },
      { title: "8-14 Day Precipitation", img: "https://www.cpc.ncep.noaa.gov/products/predictions/814day/814prcp.new.gif", link: "https://www.cpc.ncep.noaa.gov/products/predictions/814day/" } ] },
    { group: "CPC Week 3-4", items: [
      { title: "Week 3-4 Temperature",   img: "https://www.cpc.ncep.noaa.gov/products/predictions/WK34/gifs/WK34temp.gif", link: "https://www.cpc.ncep.noaa.gov/products/predictions/WK34/" },
      { title: "Week 3-4 Precipitation", img: "https://www.cpc.ncep.noaa.gov/products/predictions/WK34/gifs/WK34prcp.gif", link: "https://www.cpc.ncep.noaa.gov/products/predictions/WK34/" } ] },
    { group: "CPC Monthly", items: [
      { title: "Monthly Temperature",    img: "https://www.cpc.ncep.noaa.gov/products/predictions/30day/off14_temp.gif", link: "https://www.cpc.ncep.noaa.gov/products/predictions/30day/" },
      { title: "Monthly Precipitation",  img: "https://www.cpc.ncep.noaa.gov/products/predictions/30day/off14_prcp.gif", link: "https://www.cpc.ncep.noaa.gov/products/predictions/30day/" } ] }
  ]
};
