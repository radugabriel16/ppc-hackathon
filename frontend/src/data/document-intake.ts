import * as sdk from "../api/gen/sdk.gen";
import { ApiConnection } from "./api-client";
import type {
  DocumentIntakeConfirm,
  DocumentIntakeReject,
  CustomerCreate,
} from "../api/gen/types.gen";

export class DocumentIntakeApi {
  constructor(private readonly connection: ApiConnection) {}
  private get client() {
    return this.connection.client;
  }
  upload(
    file: File,
    customerId?: string,
    documentType?: DocumentIntakeConfirm["documentType"],
    confirmManual = false,
  ) {
    return this.connection.read(
      sdk.createCustomerDocument({
        client: this.client,
        headers: this.connection.mutationHeaders(),
        body: { file, customerId, documentType, confirmManual },
      }),
    );
  }
  batch(files: File[]) {
    return this.connection.read(
      sdk.createCustomerDocumentBatch({
        client: this.client,
        headers: this.connection.mutationHeaders(),
        body: { files },
      }),
    );
  }
  getBatch(batchId: string) {
    return this.connection.read(
      sdk.getCustomerDocumentBatch({ client: this.client, path: { batchId } }),
    );
  }
  reviews(queue: "IDENTITY" | "MANUAL", page = 0) {
    return this.connection.read(
      sdk.getDocumentReviewItems({
        client: this.client,
        query: { queue, page, size: 10 },
      }),
    );
  }
  lookup(cnp: string) {
    return this.connection.read(
      sdk.lookupDocumentCustomer({ client: this.client, query: { cnp } }),
    );
  }
  revealCnp(customerId: string) {
    return this.connection.read(
      sdk.revealCustomerCnp({
        client: this.client,
        path: { customerId },
        cache: "no-store",
      }),
    );
  }
  createCustomer(body: CustomerCreate) {
    return this.connection.read(
      sdk.createCustomer({
        client: this.client,
        headers: this.connection.mutationHeaders(),
        body,
      }),
    );
  }
  confirm(itemId: string, body: DocumentIntakeConfirm) {
    return this.connection.read(
      sdk.confirmDocumentReviewItem({
        client: this.client,
        headers: this.connection.mutationHeaders(),
        path: { itemId },
        body,
      }),
    );
  }
  reject(itemId: string, body: DocumentIntakeReject) {
    return this.connection.read(
      sdk.rejectDocumentReviewItem({
        client: this.client,
        headers: this.connection.mutationHeaders(),
        path: { itemId },
        body,
      }),
    );
  }
}

export function validCnp(value: string) {
  if (!/^[1-9][0-9]{12}$/.test(value)) return false;
  const prefix = Number(value[0]),
    yy = Number(value.slice(1, 3)),
    month = Number(value.slice(3, 5)),
    day = Number(value.slice(5, 7));
  const base = (
    { 1: 1900, 2: 1900, 3: 1800, 4: 1800, 5: 2000, 6: 2000 } as Record<
      number,
      number
    >
  )[prefix];
  const validDate = (base ? [base] : [1900, 2000]).some((century) => {
    const date = new Date(Date.UTC(century + yy, month - 1, day));
    return (
      date.getUTCFullYear() === century + yy &&
      date.getUTCMonth() === month - 1 &&
      date.getUTCDate() === day
    );
  });
  const county = Number(value.slice(7, 9));
  const key = "279146358279";
  const check =
    [...value.slice(0, 12)].reduce(
      (sum, d, i) => sum + Number(d) * Number(key[i]),
      0,
    ) % 11;
  return (
    validDate &&
    ((county >= 1 && county <= 46) || [51, 52, 70].includes(county)) &&
    Number(value.slice(9, 12)) > 0 &&
    Number(value[12]) === (check === 10 ? 1 : check)
  );
}
