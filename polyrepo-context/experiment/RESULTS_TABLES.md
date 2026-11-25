## Per trial

| Trial | Repos found (of 10) | Missed repos | Wrong repos | Decommissioned repo planned | Change/verify class correct (of 10) | Edges found (of 11) | Wrong edges | Contracts found (of 5) | Wrong contracts | Plan score (of 16) | Time to push | ACUs |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| A_t1 | 7 | lineage-service, platform-e2e, search-indexer | reporting-service | yes | 7 | 5 | 1 | 4 | 2 | 9 | 2m35s | n/a |
| A_t2 | 6 | consumption-gateway, lineage-service, platform-e2e, search-indexer | reporting-service | yes | 6 | 6 | 3 | 4 | 1 | 9 | 2m07s | n/a |
| A_t3 | 7 | lineage-service, platform-e2e, search-indexer | reporting-service | yes | 7 | 5 | 2 | 4 | 2 | 9 | 2m11s | n/a |
| B_t1 | 10 | - | notification-service, platform-catalog | no | 9 | 11 | 0 | 4 | 2 | 14 | 2m46s | n/a |
| B_t2 | 10 | - | notification-service | no | 9 | 11 | 0 | 4 | 2 | 13 | 2m48s | n/a |
| B_t3 | 10 | - | notification-service, platform-catalog | no | 9 | 11 | 0 | 4 | 2 | 14 | 2m43s | n/a |
| C_t1 | 10 | - | notification-service | no | 10 | 11 | 0 | 5 | 0 | 16 | 3m18s | n/a |
| C_t2 | 10 | - | notification-service | no | 10 | 11 | 0 | 5 | 0 | 16 | 3m36s | n/a |
| C_t3 | 10 | - | notification-service | no | 10 | 11 | 0 | 5 | 0 | 16 | 2m59s | n/a |
| D_t1 | 9 | lineage-service | reporting-service | yes | 9 | 9 | 2 | 5 | 0 | 15 | 3m12s | n/a |
| D_t2 | 10 | - | notification-service, reporting-service | yes | 10 | 11 | 1 | 5 | 0 | 15 | 2m59s | n/a |
| D_t3 | 10 | - | reporting-service | yes | 10 | 10 | 1 | 5 | 0 | 15 | 3m20s | n/a |

## Per arm (mean over trials; time is median)

| Arm | Repos found (of 10) | Wrong repos | Decommissioned repo planned | Class correct (of 10) | Edges found (of 11) | Wrong edges | Contracts found (of 5) | Wrong contracts | Plan score (of 16) | Median time |
|---|---|---|---|---|---|---|---|---|---|---|
| A | 6.7 | 1.0 | 3/3 | 6.7 | 5.3 | 2.0 | 4.0 | 1.7 | 9.0 | 2m11s |
| B | 10.0 | 1.7 | 0/3 | 9.0 | 11.0 | 0.0 | 4.0 | 2.0 | 13.7 | 2m46s |
| C | 10.0 | 1.0 | 0/3 | 10.0 | 11.0 | 0.0 | 5.0 | 0.0 | 16.0 | 3m18s |
| D | 9.7 | 1.3 | 3/3 | 9.7 | 10.0 | 1.3 | 5.0 | 0.0 | 15.0 | 3m12s |
