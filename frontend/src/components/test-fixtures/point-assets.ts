import type { Asset } from "../../data/models";
import { REGIONS } from "../../data/models";
import { mockRegions } from "../../mocks/fixtures";

// Point assets captured from the scoped frontend responses for all 18 demo segments.
const rows: [string, string, Asset["type"], [number, number]][] = [
  [
    "3d9d1eb3-af22-5e06-a49b-fd29fe35b39b",
    "d51b587b-1585-5ac7-8592-0e8b88d31fb3",
    "LINE_SEGMENT",
    [21.4178455, 44.8242935],
  ],
  [
    "65af6468-d6fb-5f8d-8e46-142722b9e387",
    "a49c53fd-04b0-5806-bfcf-5a89a5e895c6",
    "LINE_SEGMENT",
    [21.157267, 45.4407935],
  ],
  [
    "1f41c394-67c5-55d7-884e-e2b1800a95ed",
    "1aad3343-7c2b-59c7-8530-2c3b49b37a9e",
    "SUBSTATION",
    [21.2187, 45.7589],
  ],
  [
    "1f41c394-67c5-55d7-884e-e2b1800a95ed",
    "5e7e89b4-3ef5-5e1b-a61f-ed56f940e1ad",
    "SUBSTATION",
    [21.2487, 45.7889],
  ],
  [
    "1f41c394-67c5-55d7-884e-e2b1800a95ed",
    "6bb9d77b-f69c-57d2-9e55-97324411bffc",
    "TRANSFORMER",
    [21.2287, 45.7689],
  ],
  [
    "1f41c394-67c5-55d7-884e-e2b1800a95ed",
    "72103825-c17a-5f4f-822f-ac6d924b1158",
    "LINE_SEGMENT",
    [21.2387, 45.7789],
  ],
  [
    "1f41c394-67c5-55d7-884e-e2b1800a95ed",
    "f2adf106-089e-5690-8ed6-d6164c286706",
    "TRANSFORMER",
    [21.2587, 45.7989],
  ],
  [
    "a14e0131-e123-5284-90f3-bcf60c7806b6",
    "9a3661b0-a5a2-51d3-a151-aa1ab3138091",
    "LINE_SEGMENT",
    [22.10444925, 44.8809565],
  ],
  [
    "efd2d973-95ea-516d-9d8c-36da217903eb",
    "ff62a680-d001-5055-baf6-67933e7110c6",
    "LINE_SEGMENT",
    [22.0875, 45.430358285],
  ],
  [
    "34c075cf-5952-59e3-b2ae-a31bea81dd35",
    "44d4a24b-706a-541f-a2f1-4256af2220f9",
    "LINE_SEGMENT",
    [22.0875, 45.975],
  ],
  [
    "ec9000f2-1413-5234-a400-ff711ca13082",
    "abd99d79-6dc3-5b85-b6d8-58eb57e2999f",
    "LINE_SEGMENT",
    [28.14229099, 44.020079],
  ],
  [
    "434560af-21a4-57cf-8c1c-11a1b4579496",
    "54ff0cf8-a37e-5ca3-8479-2920a0c392cd",
    "LINE_SEGMENT",
    [28.0625, 44.6],
  ],
  [
    "5089b445-b84a-573c-83d6-c4ca8233327e",
    "c5a82541-21b8-50e5-9836-84f938339950",
    "LINE_SEGMENT",
    [28.0625, 45.07023607],
  ],
  [
    "977cd155-b349-51f1-bf11-befa92d48ecf",
    "1694b929-43a8-54d3-9369-2206cfe23b7c",
    "SUBSTATION",
    [28.657349213, 44.204339391],
  ],
  [
    "977cd155-b349-51f1-bf11-befa92d48ecf",
    "287e27a6-3f2e-5418-9087-471b7a5d233c",
    "LINE_SEGMENT",
    [28.659303509, 44.200619145],
  ],
  [
    "977cd155-b349-51f1-bf11-befa92d48ecf",
    "76d37672-f538-5ba5-b052-4012717ef06f",
    "SUBSTATION",
    [28.66, 44.19],
  ],
  [
    "977cd155-b349-51f1-bf11-befa92d48ecf",
    "d4860ffd-8791-50bb-8c8f-32ba3755adfb",
    "TRANSFORMER",
    [28.660253343, 44.198310548],
  ],
  [
    "977cd155-b349-51f1-bf11-befa92d48ecf",
    "f69d3e44-a7db-5542-873e-c78fce82147b",
    "TRANSFORMER",
    [28.655394917, 44.208059638],
  ],
  [
    "b005a5fc-db5a-58d8-b6b1-557ec13a7a16",
    "12793afe-94da-5663-bcda-e5b9ff3a3dcc",
    "LINE_SEGMENT",
    [28.694868748, 44.598334],
  ],
  [
    "2b82dba0-d61a-5763-9d20-9c5ba089ebe1",
    "45eee8ca-1355-5e4f-9ce0-f5d702b978dc",
    "LINE_SEGMENT",
    [29.1352185, 45.187242],
  ],
  [
    "368b7d5d-7572-57ee-90ef-ca20b10d21d0",
    "ed27b4b1-4676-53ea-9b06-7ab60b727e5a",
    "LINE_SEGMENT",
    [25.25, 44.094382315],
  ],
  [
    "9441c976-aefa-5655-99a8-be0203906a6d",
    "966a607c-2069-587d-8d4e-4fd812461ef7",
    "LINE_SEGMENT",
    [25.25, 44.6],
  ],
  [
    "b53641b8-fcca-5ccc-8625-6f05b5039ca7",
    "47830b3a-884d-5ad5-af4e-e4fcd48ef8c4",
    "LINE_SEGMENT",
    [25.25, 45.233333333],
  ],
  [
    "d107d23b-c281-5da0-8a75-0dd02c01368f",
    "0d445c8c-7290-51db-8071-1897c4ec2cdb",
    "LINE_SEGMENT",
    [26.335702268, 44.0989375],
  ],
  [
    "ef21068e-9306-5504-ae33-be5256407592",
    "32a81ba8-bd46-5df4-b6b2-05f5c0b2e33c",
    "TRANSFORMER",
    [26.1225, 44.4468],
  ],
  [
    "ef21068e-9306-5504-ae33-be5256407592",
    "35e25101-d565-59ab-b915-7dbe94e37997",
    "TRANSFORMER",
    [26.1525, 44.4768],
  ],
  [
    "ef21068e-9306-5504-ae33-be5256407592",
    "a2883034-0b23-51fa-850f-90fd86e825dd",
    "SUBSTATION",
    [26.1125, 44.4368],
  ],
  [
    "ef21068e-9306-5504-ae33-be5256407592",
    "db64fd1e-349d-5a96-bdb8-e19943ee136e",
    "SUBSTATION",
    [26.1425, 44.4668],
  ],
  [
    "ef21068e-9306-5504-ae33-be5256407592",
    "e5a4461a-3133-5cd0-9e4d-cbb6876d4066",
    "LINE_SEGMENT",
    [26.1325, 44.4568],
  ],
  [
    "0b535e18-4e01-50fc-95f2-fd198240a14b",
    "05c4d7f4-489e-5609-82bc-e135dc256d30",
    "LINE_SEGMENT",
    [26.75, 45.233333333],
  ],
];

export const pointAssetFixtures: Asset[] = rows.map(
  ([segmentId, id, type, coordinates]) => {
    const owner = mockRegions.find((region) =>
      region.subregions?.some((segment) => segment.id === segmentId),
    );
    const region = REGIONS.find((code) => code === owner?.code);
    if (!region) throw new Error(`Unknown fixture segment ${segmentId}`);
    return { id, name: `${type} ${id}`, type, coordinates, region, segmentId };
  },
);
