"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import { ApiError, submitWebsiteInquiry } from "../../lib/api";

type InquiryContext = {
  organizationId: string;
  productLineId: string;
  productName: string;
  sourceUrl: string;
};

function readInquiryContext(): InquiryContext {
  if (typeof window === "undefined") {
    return { organizationId: "", productLineId: "", productName: "", sourceUrl: "" };
  }
  const params = new URLSearchParams(window.location.search);
  return {
    organizationId: params.get("organization_id") ?? "",
    productLineId: params.get("product_line_id") ?? "",
    productName: params.get("product") ?? "our products",
    sourceUrl: window.location.href,
  };
}

export default function PublicInquiryPage() {
  const [context, setContext] = useState<InquiryContext>({
    organizationId: "",
    productLineId: "",
    productName: "",
    sourceUrl: "",
  });
  const [submitting, setSubmitting] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const [error, setError] = useState("");
  const hasRequiredContext = useMemo(
    () => Boolean(context.organizationId && context.productLineId),
    [context.organizationId, context.productLineId]
  );

  useEffect(() => {
    setContext(readInquiryContext());
  }, []);

  async function submitForm(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!hasRequiredContext) return;
    const form = new FormData(event.currentTarget);
    setSubmitting(true);
    setError("");
    try {
      await submitWebsiteInquiry(context.organizationId, {
        product_line_id: context.productLineId,
        company_name: String(form.get("company_name") ?? "").trim(),
        contact_name: String(form.get("contact_name") ?? "").trim(),
        email: String(form.get("email") ?? "").trim(),
        phone: String(form.get("phone") ?? "").trim(),
        website: String(form.get("website") ?? "").trim(),
        target_market: String(form.get("target_market") ?? "").trim(),
        message: String(form.get("message") ?? "").trim(),
        source_url: context.sourceUrl,
      });
      setSubmitted(true);
      event.currentTarget.reset();
    } catch (caught) {
      setError(caught instanceof ApiError || caught instanceof Error ? caught.message : "Submission failed");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="publicInquiryShell">
      <section className="publicInquiryIntro">
        <a className="publicBrand" href="/">
          <span>TA</span>
          <strong>TRADE AXIS</strong>
        </a>
        <div>
          <p className="sectionLabel">Supplier Inquiry</p>
          <h1>Request product information</h1>
          <p>
            Send your company details and sourcing request. The export team will review it before
            creating a CRM customer record and following up.
          </p>
        </div>
      </section>
      <section className="publicInquiryCard" aria-labelledby="public-inquiry-title">
        <div className="publicInquiryHeader">
          <div>
            <p className="sectionLabel">Inquiry Form</p>
            <h2 id="public-inquiry-title">{context.productName || "Product inquiry"}</h2>
          </div>
          <span>Manual review</span>
        </div>
        {!hasRequiredContext ? (
          <div className="emptyState">
            This inquiry link is missing organization or product configuration. Please request a new
            inquiry link from the supplier.
          </div>
        ) : submitted ? (
          <div className="publicSuccess" role="status">
            <strong>Inquiry received.</strong>
            <p>Thank you. The export team will review your request and follow up manually.</p>
            <button className="outlineButton" type="button" onClick={() => setSubmitted(false)}>
              Submit another inquiry
            </button>
          </div>
        ) : (
          <form className="publicInquiryForm" onSubmit={submitForm}>
            <label>
              Company name
              <input name="company_name" required maxLength={300} placeholder="Example Import Ltd" />
            </label>
            <label>
              Contact name
              <input name="contact_name" required maxLength={200} placeholder="Mina Lee" />
            </label>
            <label>
              Email
              <input name="email" required type="email" maxLength={320} placeholder="name@company.com" />
            </label>
            <label>
              Phone / WhatsApp
              <input name="phone" maxLength={80} placeholder="+1 555 0100" />
            </label>
            <label>
              Company website
              <input name="website" maxLength={1000} placeholder="https://example.com" />
            </label>
            <label>
              Target market
              <input name="target_market" maxLength={120} placeholder="Germany, Korea, United States" />
            </label>
            <label className="wideField">
              Sourcing request
              <textarea
                name="message"
                required
                maxLength={4000}
                placeholder="Tell us product model, quantity, target price, certification needs, and timeline."
              />
            </label>
            {error && <div className="errorBanner publicError" role="alert">{error}</div>}
            <button className="primaryButton" type="submit" disabled={submitting}>
              {submitting ? "Submitting..." : "Submit inquiry"}
            </button>
          </form>
        )}
      </section>
    </main>
  );
}
