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
