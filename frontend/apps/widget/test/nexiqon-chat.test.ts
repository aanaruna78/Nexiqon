import "../src/nexiqon-chat";
import type { NexiqonChat } from "../src/nexiqon-chat";

async function mount(attrs = ""): Promise<NexiqonChat> {
  document.body.innerHTML = `<nexiqon-chat ${attrs}></nexiqon-chat>`;
  const el = document.querySelector("nexiqon-chat")!;
  await el.updateComplete;
  return el;
}

describe("<nexiqon-chat>", () => {
  it("registers the custom element", () => {
    expect(customElements.get("nexiqon-chat")).toBeDefined();
  });

  it("renders in shadow DOM with a closed panel", async () => {
    const el = await mount('agent="support"');
    const button = el.shadowRoot!.querySelector("button")!;
    expect(button.getAttribute("aria-expanded")).toBe("false");
    expect(el.shadowRoot!.querySelector("section")).toBeNull();
  });

  it("opens and closes, emitting events", async () => {
    const el = await mount('agent="support"');
    const seen: boolean[] = [];
    el.addEventListener("nexiqon-toggle", (e) => seen.push((e as CustomEvent).detail.open));
    el.shadowRoot!.querySelector("button")!.click();
    await el.updateComplete;
    expect(el.shadowRoot!.querySelector('section[role="dialog"]')).not.toBeNull();
    expect(el.shadowRoot!.textContent).toContain("support");
    el.shadowRoot!.querySelector("button")!.click();
    await el.updateComplete;
    expect(seen).toEqual([true, false]);
  });
});
