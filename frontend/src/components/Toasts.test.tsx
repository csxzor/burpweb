import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Toasts } from "./Toasts";

test("errors are announced as alerts and info as status, both as text", () => {
  render(
    <Toasts
      toasts={[
        { id: 1, level: "error", message: "<b>address already in use</b>" },
        { id: 2, level: "info", message: "Opened Firefox" },
      ]}
      onDismiss={vi.fn()}
    />,
  );
  expect(screen.getByRole("alert")).toHaveTextContent("<b>address already in use</b>");
  expect(document.querySelector("b")).toBeNull();
  expect(screen.getByRole("status")).toHaveTextContent("Opened Firefox");
});

test("the dismiss button reports the toast id", async () => {
  const onDismiss = vi.fn();
  render(<Toasts toasts={[{ id: 7, level: "error", message: "boom" }]} onDismiss={onDismiss} />);
  await userEvent.click(screen.getByRole("button", { name: "Dismiss" }));
  await waitFor(() => expect(onDismiss).toHaveBeenCalledWith(7));
});
