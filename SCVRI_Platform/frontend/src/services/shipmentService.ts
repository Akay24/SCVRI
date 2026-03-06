export const shipmentService = {
  // Delayed shipments by transport mode
  delays: async () => [
    { name: "SEA",  value: 18 },
    { name: "AIR",  value: 5  },
    { name: "RAIL", value: 9  },
    { name: "ROAD", value: 12 },
  ],
  // On-time vs delayed by week (last 8 weeks)
  onTimeByWeek: async () => [
    { name: "W45", onTime: 84, delayed: 16 },
    { name: "W46", onTime: 80, delayed: 20 },
    { name: "W47", onTime: 82, delayed: 18 },
    { name: "W48", onTime: 77, delayed: 23 },
    { name: "W49", onTime: 79, delayed: 21 },
    { name: "W50", onTime: 75, delayed: 25 },
    { name: "W51", onTime: 71, delayed: 29 },
    { name: "W52", onTime: 73, delayed: 27 },
  ],
};
