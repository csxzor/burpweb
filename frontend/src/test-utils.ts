/** Stands in for the browser WebSocket in every test; see test-setup.ts. */
export class FakeWebSocket {
  static instances: FakeWebSocket[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((e: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  closed = false;

  constructor(public url: string) {
    FakeWebSocket.instances.push(this);
  }
  close() {
    this.closed = true;
  }
  open() {
    this.onopen?.();
  }
  emit(event: unknown) {
    this.onmessage?.({ data: JSON.stringify(event) });
  }
  drop() {
    this.onclose?.();
  }
}
