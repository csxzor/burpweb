import { notifyAuthStatus } from "./api";

export interface UploadHandle {
  promise: Promise<void>;
  abort: () => void;
}

function errorMessage(xhr: XMLHttpRequest): string {
  try {
    const message = JSON.parse(xhr.responseText).error;
    if (message) return String(message);
  } catch {
    // not JSON
  }
  return `Upload failed (HTTP ${xhr.status})`;
}

/** Streams a file to the backend as the raw request body, so a 160+ MB export never sits in memory. */
export function uploadFile(
  id: string,
  file: File,
  onProgress: (loaded: number, total: number) => void,
  makeXhr: () => XMLHttpRequest = () => new XMLHttpRequest(),
): UploadHandle {
  const xhr = makeXhr();
  const promise = new Promise<void>((resolve, reject) => {
    xhr.open("PUT", `/api/uploads/${encodeURIComponent(id)}?name=${encodeURIComponent(file.name)}`);
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable) onProgress(event.loaded, event.total);
    };
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        onProgress(file.size, file.size);
        resolve();
        return;
      }
      notifyAuthStatus(xhr.status);
      reject(new Error(errorMessage(xhr)));
    };
    xhr.onerror = () => reject(new Error("Network error while uploading"));
    xhr.onabort = () => reject(new Error("Upload cancelled"));
    xhr.send(file);
  });
  return { promise, abort: () => xhr.abort() };
}
