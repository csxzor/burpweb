import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ApiError, api } from "../api";
import { Unlock, passphraseStrength } from "./Unlock";

afterEach(() => {
  vi.restoreAllMocks();
  localStorage.clear();
  sessionStorage.clear();
});

test("strength labels", () => {
  expect(passphraseStrength("short")).toEqual({ level: 0, label: "Too short" });
  expect(passphraseStrength("abcdefghij").label).toBe("Fair");
  expect(passphraseStrength("abcdefghijkl").label).toBe("Good");
  expect(passphraseStrength("Abcdefghijk1").label).toBe("Good");
  expect(passphraseStrength("Abcdefghijklmnop1!").label).toBe("Strong");
});

test("creating needs a long enough, matching passphrase and shows the warning", async () => {
  const create = vi.spyOn(api, "createVault").mockResolvedValue({ ok: true });
  const onUnlocked = vi.fn();
  render(<Unlock mode="new" onUnlocked={onUnlocked} />);
  expect(screen.getByText(/can't be recovered/)).toBeInTheDocument();
  const submit = screen.getByRole("button", { name: "Create library" });
  expect(submit).toBeDisabled();
  await userEvent.type(screen.getByLabelText("Passphrase"), "correct horse battery");
  expect(submit).toBeDisabled();
  await userEvent.type(screen.getByLabelText("Confirm passphrase"), "correct horse batterX");
  expect(screen.getByRole("alert")).toHaveTextContent("Passphrases don't match");
  await userEvent.clear(screen.getByLabelText("Confirm passphrase"));
  await userEvent.type(screen.getByLabelText("Confirm passphrase"), "correct horse battery");
  expect(submit).toBeEnabled();
  await userEvent.click(submit);
  expect(create).toHaveBeenCalledWith("correct horse battery");
  await waitFor(() => expect(onUnlocked).toHaveBeenCalled());
});

test("a passphrase shorter than the minimum cannot be submitted", async () => {
  render(<Unlock mode="new" onUnlocked={vi.fn()} />);
  await userEvent.type(screen.getByLabelText("Passphrase"), "short");
  await userEvent.type(screen.getByLabelText("Confirm passphrase"), "short");
  expect(screen.getByRole("button", { name: "Create library" })).toBeDisabled();
});

test("a wrong passphrase shows an error and empties the field", async () => {
  vi.spyOn(api, "unlock").mockRejectedValue(new ApiError(401, "wrong passphrase"));
  render(<Unlock mode="locked" onUnlocked={vi.fn()} />);
  const field = screen.getByLabelText("Passphrase");
  await userEvent.type(field, "nope-nope-nope{Enter}");
  expect(await screen.findByRole("alert")).toHaveTextContent("Wrong passphrase");
  expect(field).toHaveValue("");
});

test("test_passphrase_is_cleared_and_never_stored", async () => {
  vi.spyOn(api, "unlock").mockResolvedValue({ ok: true });
  const { container } = render(<Unlock mode="locked" onUnlocked={() => {}} />);
  const field = screen.getByLabelText("Passphrase");
  expect(field).toHaveAttribute("type", "password");
  await userEvent.type(field, "my secret passphrase");
  await userEvent.click(screen.getByRole("button", { name: "Unlock" }));
  expect(field).toHaveValue("");
  expect(localStorage.length).toBe(0);
  expect(sessionStorage.length).toBe(0);
  expect(window.location.href).not.toContain("secret");
  expect(container.innerHTML).not.toContain("my secret passphrase");
});

test("a second submit while the first is pending is ignored", async () => {
  let release!: () => void;
  const unlock = vi.spyOn(api, "unlock").mockImplementation(
    () => new Promise((resolve) => { release = () => resolve({ ok: true }); }),
  );
  render(<Unlock mode="locked" onUnlocked={vi.fn()} />);
  await userEvent.type(screen.getByLabelText("Passphrase"), "my secret passphrase{Enter}");
  await userEvent.type(screen.getByLabelText("Passphrase"), "again again again{Enter}");
  expect(unlock).toHaveBeenCalledTimes(1);
  release();
});
