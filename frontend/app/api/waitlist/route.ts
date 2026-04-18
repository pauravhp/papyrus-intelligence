import { NextRequest, NextResponse } from "next/server";
import { Resend } from "resend";

export async function POST(req: NextRequest) {
  const body = await req.json().catch(() => null);
  const email: unknown = body?.email;
  const firstName: unknown = body?.firstName;

  if (typeof email !== "string" || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
    return NextResponse.json({ error: "A valid email is required." }, { status: 400 });
  }

  const apiKey = process.env.RESEND_API_KEY;
  if (!apiKey) {
    console.error("RESEND_API_KEY not configured");
    return NextResponse.json({ error: "Service unavailable." }, { status: 503 });
  }

  const resend = new Resend(apiKey);
  const { error } = await resend.contacts.create({
    email,
    firstName: typeof firstName === "string" ? firstName.trim() : undefined,
    unsubscribed: false,
  });

  if (error) {
    console.error("Resend contacts error", error);
    return NextResponse.json({ error: "Could not save your details. Please try again." }, { status: 500 });
  }

  return NextResponse.json({ ok: true });
}
