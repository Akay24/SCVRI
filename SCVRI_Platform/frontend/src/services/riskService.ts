export const riskService = {
  // 13-week platform-wide risk score trend
  trend: async () => [
    { name: "W40", value: 41 },
    { name: "W41", value: 39 },
    { name: "W42", value: 44 },
    { name: "W43", value: 47 },
    { name: "W44", value: 43 },
    { name: "W45", value: 50 },
    { name: "W46", value: 55 },
    { name: "W47", value: 52 },
    { name: "W48", value: 61 },
    { name: "W49", value: 58 },
    { name: "W50", value: 64 },
    { name: "W51", value: 70 },
    { name: "W52", value: 67 },
  ],
  // Risk score by region
  byRegion: async () => [
    { name: "AMER",  value: 38 },
    { name: "EU",    value: 44 },
    { name: "EMEA",  value: 63 },
    { name: "APAC",  value: 71 },
  ],
  // Risk score by category/driver
  byDriver: async () => [
    { name: "Weather",      value: 28 },
    { name: "Financial",    value: 22 },
    { name: "Transport",    value: 19 },
    { name: "Geopolitical", value: 14 },
    { name: "ESG",          value: 9  },
    { name: "Capacity",     value: 8  },
  ],
};
