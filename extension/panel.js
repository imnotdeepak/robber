const ADVISOR = "http://127.0.0.1:8765/";

async function connect() {
  try {
    const res = await fetch(ADVISOR + "api/state", { cache: "no-store" });
    if (!res.ok) throw new Error(res.statusText);
    const frame = document.getElementById("advisor");
    if (!frame.src) frame.src = ADVISOR;
    frame.style.display = "block";
    document.getElementById("offline").style.display = "none";
  } catch {
    document.getElementById("advisor").style.display = "none";
    document.getElementById("offline").style.display = "block";
  }
}
document.getElementById("retry").onclick = connect;
connect();
