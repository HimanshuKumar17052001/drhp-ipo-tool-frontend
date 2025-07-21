### Frontend Changes (Next.js React)

Now, let's update your `app/page.tsx` to use this new backend functionality.

\`\`\`typescriptreact file="app/page.tsx"
[v0-no-op-code-block-prefix]"use client"

import type React from "react"

import { useState, useRef, useCallback } from "react"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { Progress } from "@/components/ui/progress"
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog"
import { Badge } from "@/components/ui/badge"
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu"
import { Upload, FileText, Download, Building2, Trash2, Play, X, AlertCircle, Loader2, Users, ChevronDown, ZoomIn, ZoomOut, RotateCw, ChevronLeft, ChevronRight, Eye } from 'lucide-react'

interface Company {
  id: string
  name: string
  uin: string
  uploadDate: string
  status: "processing" | "completed" | "failed"
  hasMarkdown: boolean
}

interface ProcessingStatus {
  stage: "pages" | "qdrant" | "checklist" | "markdown" | "completed"
  progress: number
  message: string
}

type LeftPaneState = "upload" | "loading" | "preview"

export default function DRHPIPOTool() {
  const [uploadedFile, setUploadedFile] = useState<File | null>(null)
  const [pdfPreviewUrl, setPdfPreviewUrl] = useState<string>("")
  const [leftPaneState, setLeftPaneState] = useState<LeftPaneState>("upload")
  const [isProcessing, setIsProcessing] = useState(false)
  const [processingStatus, setProcessingStatus] = useState<ProcessingStatus | null>(null)
  const [generatedIPO, setGeneratedIPO] = useState<string>("")
  const [companies, setCompanies] = useState<Company[]>([
    {
      id: "1",
      name: "TechCorp Solutions Ltd.",
      uin: "TC001234567890",
      uploadDate: "2024-01-15",
      status: "completed",
      hasMarkdown: true,
    },
    {
      id: "2",
      name: "GreenEnergy Innovations",
      uin: "GE009876543210",
      uploadDate: "2024-01-10",
      status: "completed",
      hasMarkdown: true,
    },
    {
      id: "3",
      name: "FinTech Dynamics Pvt Ltd",
      uin: "FT005555444433",
      uploadDate: "2024-01-12",
      status: "processing",
      hasMarkdown: false,
    },
  ])
  const [selectedCompany, setSelectedCompany] = useState<Company | null>(null)
  const [isGeneratingNotes, setIsGeneratingNotes] = useState(false)
  const [showCompanyDetail, setShowCompanyDetail] = useState(false)
  const [selectedCompanyDetail, setSelectedCompanyDetail] = useState<Company | null>(null)
  const [companyReport, setCompanyReport] = useState<string>("")
  const [isLoadingCompanyReport, setIsLoadingCompanyReport] = useState(false)
  const [generatedPdfBlobUrl, setGeneratedPdfBlobUrl] = useState<string>("");
  const [companyReportPdfBlobUrl, setCompanyReportPdfBlobUrl] = useState<string>("");
  const [isGeneratingPdf, setIsGeneratingPdf] = useState(false);

  // PDF Viewer states
  const [currentPage, setCurrentPage] = useState<number>(1)
  const [totalPages, setTotalPages] = useState<number>(0)
  const [scale, setScale] = useState<number>(1.0)
  const [rotation, setRotation] = useState<number>(0)

  // Dialog states
  const [showGenerateConfirm, setShowGenerateConfirm] = useState(false)
  const [showRemoveConfirm, setShowRemoveConfirm] = useState(false)
  const [showWarning, setShowWarning] = useState<string>("")

  const fileInputRef = useRef<HTMLInputElement>(null)
  const [isDragOver, setIsDragOver] = useState(false)

  // Simulate API calls
  const simulateProcessing = useCallback(async () => {
    setIsGeneratingNotes(true);
    setIsGeneratingPdf(true); // Start PDF generation loading

    const stages = [
      { stage: "pages" as const, progress: 25, message: "Extracting and saving PDF pages..." },
      { stage: "qdrant" as const, progress: 50, message: "Creating vector embeddings..." },
      { stage: "checklist" as const, progress: 75, message: "Running AI checklist processor..." },
      { stage: "markdown" as const, progress: 90, message: "Generating final markdown report..." },
      { stage: "completed" as const, progress: 100, message: "IPO Notes generated successfully!" },
    ];

    for (const status of stages) {
      setProcessingStatus(status);
      await new Promise((resolve) => setTimeout(resolve, 2000));
    }

    const sampleIPO = `
# IPO Investment Note
## ${uploadedFile?.name.replace(".pdf", "") || "Sample Company"}

### Executive Summary
This IPO represents a compelling investment opportunity in the technology sector. The company demonstrates strong fundamentals with consistent revenue growth and market leadership position.

### Key Investment Highlights
- **Market Leadership**: Dominant position in emerging technology sector
- **Financial Performance**: 35% revenue CAGR over past 3 years
- **Strong Management**: Experienced leadership team with proven track record
- **Growth Potential**: Expanding into high-growth international markets

### Financial Overview
- **Revenue (FY2023)**: ₹2,450 Cr (+28% YoY)
- **EBITDA Margin**: 22.5%
- **Net Profit**: ₹385 Cr (+42% YoY)
- **Debt-to-Equity**: 0.3x

### Risk Factors
- Market competition intensity
- Regulatory changes in key markets
- Technology disruption risks
- Currency fluctuation exposure

### Recommendation
**BUY** - Strong fundamentals and growth prospects justify premium valuation.

### Price Band & Valuation
- **Price Band**: ₹450 - ₹485 per share
- **Market Cap**: ₹12,500 Cr (at upper band)
- **P/E Ratio**: 32.4x (FY2023)

---
*Generated by DRHP Analysis Engine*
      `;

      try {
        const response = await fetch("http://localhost:8000/generate-report-pdf/", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            markdown_content: sampleIPO,
            company_name: uploadedFile?.name.replace(".pdf", "") || "Sample Company",
            output_filename: `IPO_Notes_${uploadedFile?.name.replace(".pdf", "") || "Report"}.pdf`,
          }),
        });

        if (!response.ok) {
          throw new Error(`HTTP error! status: ${response.status}`);
        }

        const blob = await response.blob();
        const url = URL.createObjectURL(blob);
        setGeneratedPdfBlobUrl(url);
      } catch (error) {
        console.error("Failed to generate PDF:", error);
        setShowWarning("Failed to generate PDF report. Please try again.");
      } finally {
        setIsProcessing(false);
        setIsGeneratingNotes(false);
        setIsGeneratingPdf(false); // End PDF generation loading
      }
    }, [uploadedFile]);

  const handleFileUpload = async (file: File) => {
    if (file.type !== "application/pdf") {
      setShowWarning("Please upload a PDF file only.")
      return
    }

    setLeftPaneState("loading")

    // Simulate file processing delay
    await new Promise((resolve) => setTimeout(resolve, 2000))

    setUploadedFile(file)
    const url = URL.createObjectURL(file)
    setPdfPreviewUrl(url)
    setLeftPaneState("preview")
    setGeneratedIPO("")
    setProcessingStatus(null)
    setCurrentPage(1)
    setTotalPages(10) // Simulate total pages
    setScale(1.0)
    setRotation(0)
  }

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    setIsDragOver(false)
    const files = Array.from(e.dataTransfer.files)
    if (files.length > 0) {
      handleFileUpload(files[0])
    }
  }, [])

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    setIsDragOver(true)
  }, [])

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    setIsDragOver(false)
  }, [])

  const handleGenerateIPO = () => {
    if (!uploadedFile) {
      setShowWarning("Please upload a DRHP PDF file first.")
      return
    }
    setShowGenerateConfirm(true)
  }

  const confirmGenerate = () => {
    setShowGenerateConfirm(false)
    setIsProcessing(true)
    simulateProcessing()
  }

  const handleRemovePDF = () => {
    setShowRemoveConfirm(true)
  }

  const confirmRemove = () => {
    setUploadedFile(null)
    setPdfPreviewUrl("")
    setLeftPaneState("upload")
    setGeneratedIPO("") // Keep this for now, though it won't be used for display
    setProcessingStatus(null)
    setSelectedCompany(null)
    setShowRemoveConfirm(false)
    if (pdfPreviewUrl) {
      URL.revokeObjectURL(pdfPreviewUrl)
    }
    if (generatedPdfBlobUrl) { // Revoke generated PDF URL
      URL.revokeObjectURL(generatedPdfBlobUrl);
      setGeneratedPdfBlobUrl("");
    }
    if (companyReportPdfBlobUrl) { // Revoke company report PDF URL
      URL.revokeObjectURL(companyReportPdfBlobUrl);
      setCompanyReportPdfBlobUrl("");
    }
  }

  const handleCompanySelect = (company: Company) => {
    if (company.status === "processing") return;

    setSelectedCompanyDetail(company);
    setShowCompanyDetail(true);
    setCompanyReportPdfBlobUrl(""); // Clear previous report
    setIsLoadingCompanyReport(true);

    if (company.hasMarkdown) {
      // Simulate fetching markdown from database (replace with actual fetch if needed)
      const fetchedMarkdown = `
# IPO Investment Note
## ${company.name}

### Executive Summary
Previously generated IPO analysis for ${company.name}. This analysis was completed on ${company.uploadDate}.

### Key Investment Highlights
- Comprehensive DRHP analysis completed
- Financial metrics evaluated
- Risk assessment performed
- Investment recommendation provided

### Status
**Analysis Complete** - Full IPO notes available for review.

---
*Generated by DRHP Analysis Engine*
*Last Updated: ${company.uploadDate}*
        `;

      // Now, generate PDF from this markdown
      fetch("http://localhost:8000/generate-report-pdf/", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          markdown_content: fetchedMarkdown,
          company_name: company.name,
          output_filename: `${company.name.replace(/[^a-zA-Z0-9]/g, '_')}_IPO_Notes.pdf`,
        }),
      })
        .then((response) => {
          if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
          }
          return response.blob();
        })
        .then((blob) => {
          const url = URL.createObjectURL(blob);
          setCompanyReportPdfBlobUrl(url);
        })
        .catch((error) => {
          console.error("Failed to generate company report PDF:", error);
          setShowWarning("Failed to load company report PDF. Please try again.");
        })
        .finally(() => {
          setIsLoadingCompanyReport(false);
        });
    } else {
      setIsLoadingCompanyReport(false);
    }
  };

  const handleRegenerateReport = () => {
    if (selectedCompanyDetail) {
      setIsLoadingCompanyReport(true);
      setCompanyReportPdfBlobUrl(""); // Clear previous report

      // Simulate report regeneration markdown
      const regeneratedMarkdown = `
# IPO Investment Note (Regenerated)
## ${selectedCompanyDetail.name}

### Executive Summary
Newly regenerated IPO analysis for ${selectedCompanyDetail.name}. This updated analysis includes the latest market data and financial metrics.

### Key Investment Highlights
- Updated market analysis completed
- Latest financial metrics evaluated
- Current risk assessment performed
- Revised investment recommendation provided

### Status
**Analysis Updated** - Fresh IPO notes with latest data.

---
*Generated by DRHP Analysis Engine*
*Regenerated on: ${new Date().toLocaleDateString()}*
        `;

      // Now, generate PDF from this markdown
      fetch("http://localhost:8000/generate-report-pdf/", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          markdown_content: regeneratedMarkdown,
          company_name: selectedCompanyDetail.name,
          output_filename: `${selectedCompanyDetail.name.replace(/[^a-zA-Z0-9]/g, '_')}_IPO_Notes_Regenerated.pdf`,
        }),
      })
        .then((response) => {
          if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
          }
          return response.blob();
        })
        .then((blob) => {
          const url = URL.createObjectURL(blob);
          setCompanyReportPdfBlobUrl(url);
        })
        .catch((error) => {
          console.error("Failed to regenerate company report PDF:", error);
          setShowWarning("Failed to regenerate PDF report. Please try again.");
        })
        .finally(() => {
          setIsLoadingCompanyReport(false);
        });
    }
  }

  const handleDeleteCompany = () => {
    if (selectedCompanyDetail) {
      setCompanies((prev) => prev.filter((c) => c.id !== selectedCompanyDetail.id))
      setShowCompanyDetail(false)
      setSelectedCompanyDetail(null)
      setCompanyReport("")
    }
  }

  const cancelProcessing = () => {
    setIsProcessing(false)
    setProcessingStatus(null)
  }

  const downloadPDF = async () => {
    if (!generatedPdfBlobUrl) {
      setShowWarning("No IPO notes PDF generated yet.");
      return;
    }

    try {
      // We already have the blob URL, so just trigger download
      const a = document.createElement("a");
      a.href = generatedPdfBlobUrl;
      a.download = `IPO_Notes_${uploadedFile?.name.replace(".pdf", "") || "Report"}.pdf`;
      document.body.appendChild(a); // Required for Firefox
      a.click();
      document.body.removeChild(a); // Clean up
    } catch (error) {
      console.error("Failed to download PDF:", error);
      setShowWarning("Failed to download PDF report. Please try again.");
    }
  };

  const goToPrevPage = () => {
    setCurrentPage((prev) => Math.max(prev - 1, 1))
  }

  const goToNextPage = () => {
    setCurrentPage((prev) => Math.min(prev + 1, totalPages))
  }

  const zoomIn = () => {
    setScale((prev) => Math.min(prev + 0.2, 3.0))
  }

  const zoomOut = () => {
    setScale((prev) => Math.max(prev - 0.2, 0.5))
  }

  const rotate = () => {
    setRotation((prev) => (prev + 90) % 360)
  }

  const renderLeftPane = () => {
    switch (leftPaneState) {
      case "upload":
        return (
          <div className="h-full flex flex-col p-6">
            <div className="text-center mb-4 shrink-0">
              <h2 className="text-[#023047] text-xl font-bold drop-shadow-sm">DRHP Document Upload</h2>
              <p className="text-gray-500 text-sm mt-1">Upload your DRHP PDF document to get started</p>
            </div>

            <div
              className={`border-dashed flex-grow text-center transition-all duration-300 depth-upload cursor-pointer rounded-xl border-2 flex flex-col items-center justify-center ${
                isDragOver
                  ? "border-[#FFB703] bg-[#FFB703]/10 scale-[1.02]"
                  : "border-gray-300 hover:border-[#219EBC] hover:bg-[#219EBC]/5"
              }`}
              onDrop={handleDrop}
              onDragOver={handleDragOver}
              onDragLeave={handleDragLeave}
              onClick={() => fileInputRef.current?.click()}
            >
              <Upload className="w-16 h-16 mb-4 text-gray-400" />
              <h3 className="font-semibold text-lg text-gray-700">Drop DRHP PDF here</h3>
              <p className="text-sm text-gray-400 italic my-2">or click to browse files</p>
              <Button
                variant="outline"
                size="lg"
                className="border-[#219EBC] text-[#219EBC] hover:bg-[#219EBC] hover:text-white bg-transparent depth-button px-10 py-2 text-base mt-4"
              >
                Browse Files
              </Button>
              <input
                ref={fileInputRef}
                type="file"
                accept=".pdf"
                className="hidden"
                onChange={(e) => {
                  const file = e.target.files?.[0]
                  if (file) handleFileUpload(file)
                }}
              />
            </div>
          </div>
        )

      case "loading":
        return (
          <div className="h-full flex items-center justify-center">
            <div className="text-center">
              <div className="relative mb-8">
                <div className="w-24 h-24 border-4 border-[#219EBC]/20 rounded-full animate-spin border-t-[#219EBC] mx-auto"></div>
                <FileText className="w-10 h-10 absolute top-1/2 left-1/2 transform -translate-x-1/2 -translate-y-1/2 text-[#219EBC]" />
              </div>
              <h3 className="text-2xl font-semibold mb-3 text-[#023047]">Processing Document...</h3>
              <p className="text-gray-600 text-lg">Please wait while we prepare your PDF for viewing</p>
            </div>
          </div>
        )

      case "preview":
        return (
          <div className="h-full flex flex-col">
            {/* PDF Controls */}
            <div className="p-2 border-b bg-gradient-to-r from-[#5CAE6]/10 to-[#219EBC]/10 flex items-center justify-between flex-wrap gap-2">
              <div className="flex items-center space-x-2">
                <div className="flex items-center space-x-1 bg-white rounded-lg p-1 depth-button">
                  <Button variant="ghost" size="sm" onClick={goToPrevPage} disabled={currentPage <= 1}>
                    <ChevronLeft className="w-4 h-4" />
                  </Button>
                  <span className="px-2 text-sm font-medium">
                    {currentPage} / {totalPages}
                  </span>
                  <Button variant="ghost" size="sm" onClick={goToNextPage} disabled={currentPage >= totalPages}>
                    <ChevronRight className="w-4 h-4" />
                  </Button>
                </div>

                <div className="flex items-center space-x-1 bg-white rounded-lg p-1 depth-button">
                  <Button variant="ghost" size="sm" onClick={zoomOut} disabled={scale <= 0.5}>
                    <ZoomOut className="w-4 h-4" />
                  </Button>
                  <span className="px-2 text-sm font-medium">{Math.round(scale * 100)}%</span>
                  <Button variant="ghost" size="sm" onClick={zoomIn} disabled={scale >= 3.0}>
                    <ZoomIn className="w-4 h-4" />
                  </Button>
                </div>

                <Button variant="ghost" size="sm" onClick={rotate} className="bg-white depth-button">
                  <RotateCw className="w-4 h-4" />
                </Button>
              </div>

              <div className="flex items-center space-x-2">
                <Button variant="destructive" size="sm" onClick={handleRemovePDF} className="depth-button">
                  <Trash2 className="w-3 h-3 mr-1" />
                  Remove
                </Button>
                <Button
                  onClick={handleGenerateIPO}
                  disabled={isProcessing}
                  size="sm"
                  className="bg-gradient-to-r from-[#FFB703] to-[#FB8500] hover:from-[#FB8500] hover:to-[#FFB703] text-white depth-button glow-orange"
                >
                  {isProcessing ? <Loader2 className="w-3 h-3 mr-1 animate-spin" /> : <Play className="w-3 h-3 mr-1" />}
                  Generate IPO Notes
                </Button>
              </div>
            </div>

            {/* PDF Viewer - Using iframe as fallback */}
            <div className="flex-1 overflow-auto bg-gray-100 p-2">
              <div className="flex justify-center">
                <div className="depth-content bg-white rounded-lg shadow-lg w-full max-w-4xl">
                  {pdfPreviewUrl ? (
                    <div
                      className="w-full h-full min-h-[600px] rounded-lg overflow-hidden"
                      style={{
                        transform: `scale(${scale}) rotate(${rotation}deg)`,
                        transformOrigin: "center center",
                        transition: "transform 0.2s ease",
                      }}
                    >
                      <iframe
                        src={`${pdfPreviewUrl}#page=${currentPage}&zoom=${Math.round(scale * 100)}`}
                        className="w-full h-full border-0 rounded-lg"
                        title="PDF Preview"
                        style={{ minHeight: "600px" }}
                      />
                    </div>
                  ) : (
                    <div className="flex items-center justify-center p-8 min-h-[600px]">
                      <div className="text-center text-gray-500">
                        <Eye className="w-12 h-12 mx-auto mb-3" />
                        <h3 className="text-lg font-medium mb-2">PDF Preview</h3>
                        <p className="text-sm">Your PDF document will appear here</p>
                      </div>
                    </div>
                  )}
                </div>
              </div>
            </div>
          </div>
        )

      default:
        return null
    }
  }

  return (
    <div className="min-h-screen enhanced-bg">
      {/* Navigation Bar */}
      <nav className="bg-gradient-to-r from-[#219EBC] to-[#023047] px-4 py-2 depth-nav float-animation">
        <div className="flex items-center justify-between">
          <div className="flex items-center">
            <h1 className="text-lg font-semibold text-white drop-shadow-lg">DRHP IPO Notes Generator</h1>
          </div>

          <div className="flex items-center space-x-2">
            <Button
              variant="outline"
              size="sm"
              className="bg-white/10 hover:bg-white/20 text-white border-white/20 depth-button glow-blue"
            >
              <Upload className="w-4 h-4 mr-1" />
              Upload Company Logo
            </Button>
            <Button
              variant="outline"
              size="sm"
              className="bg-white/10 hover:bg-white/20 text-white border-white/20 depth-button glow-blue"
            >
              <Building2 className="w-4 h-4 mr-1" />
              Upload Entity Logo
            </Button>

            {/* Companies Dropdown */}
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button
                  variant="outline"
                  size="sm"
                  className="bg-white/10 hover:bg-white/20 text-white border-white/20 depth-button glow-blue"
                >
                  <Users className="w-4 h-4 mr-1" />
                  View Companies
                  <ChevronDown className="w-4 h-4 ml-1" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent className="w-80 max-h-96 overflow-auto depth-dropdown">
                {companies.map((company) => (
                  <DropdownMenuItem
                    key={company.id}
                    className={`flex flex-col items-start p-3 shimmer-effect ${
                      company.status === "processing"
                        ? "cursor-not-allowed opacity-50"
                        : "cursor-pointer hover:bg-gray-50"
                    }`}
                    onClick={() => handleCompanySelect(company)}
                    disabled={company.status === "processing"}
                  >
                    <div className="w-full">
                      <div className="flex items-center justify-between mb-1">
                        <span className="font-medium text-sm">{company.name}</span>
                        <Badge
                          variant="outline"
                          className={`text-xs depth-badge ${
                            company.status === "completed"
                              ? "bg-green-50 text-green-700 border-green-200"
                              : "bg-blue-50 text-blue-700 border-blue-200"
                          }`}
                        >
                          {company.status.toUpperCase()}
                        </Badge>
                      </div>
                      <div className="text-xs text-gray-500 space-y-1">
                        <div>UIN: {company.uin}</div>
                        <div>Uploaded: {company.uploadDate}</div>
                      </div>
                    </div>
                  </DropdownMenuItem>
                ))}
              </DropdownMenuContent>
            </DropdownMenu>

            <Button
              variant="outline"
              size="sm"
              onClick={downloadPDF}
              className="bg-white/10 hover:bg-white/20 text-white border-white/20 depth-button glow-blue"
            >
              <Download className="w-4 h-4 mr-1" />
              Download as PDF
            </Button>
          </div>
        </div>
      </nav>

      {/* Main Content */}
      <div className="flex h-[calc(100vh-60px)]">
        {/* Left Frame - Dynamic Content */}
        <div className="w-1/2 border-r border-gray-200 p-1">
          <Card className="h-full border-0 depth-card shimmer-effect">{renderLeftPane()}</Card>
        </div>

        {/* Right Frame - IPO Notes Display */}
        <div className="w-1/2 p-1">
          <Card className="h-full flex flex-col border-0 depth-card shimmer-effect">
            <div className="p-3 border-b bg-gradient-to-r from-[#023047]/10 to-[#219EBC]/10 rounded-t-md">
              <div className="flex items-center justify-between">
                <h2 className="text-base font-medium text-[#023047] drop-shadow-sm">Generated IPO Notes</h2>
                {selectedCompany && (
                  <Badge variant="secondary" className="text-xs depth-badge">
                    {selectedCompany.name}
                  </Badge>
                )}
              </div>

              {/* Processing Status */}
              {isProcessing && processingStatus && (
                <div className="mt-3 space-y-2 depth-status p-3 rounded-lg border border-gray-200 bg-white/50">
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-medium">{processingStatus.message}</span>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={cancelProcessing}
                      className="depth-button bg-transparent"
                    >
                      <X className="w-3 h-3 mr-1" />
                      Cancel
                    </Button>
                  </div>
                  <Progress value={processingStatus.progress} className="h-1 enhanced-progress" />
                  <div className="flex justify-between text-xs text-gray-500">
                    <span className={processingStatus.stage === "pages" ? "font-medium text-[#FFB703]" : ""}>
                      Pages
                    </span>
                    <span className={processingStatus.stage === "qdrant" ? "font-medium text-[#FFB703]" : ""}>
                      Qdrant
                    </span>
                    <span className={processingStatus.stage === "checklist" ? "font-medium text-[#FFB703]" : ""}>
                      Checklist
                    </span>
                    <span className={processingStatus.stage === "markdown" ? "font-medium text-[#FFB703]" : ""}>
                      Markdown
                    </span>
                  </div>
                </div>
              )}
            </div>

            {/* IPO Notes Content */}
            <div className="flex-1 p-3 overflow-auto">
              {!generatedPdfBlobUrl && !isProcessing && !isGeneratingNotes ? (
                <div className="h-full flex items-center justify-center">
                  <div className="text-center text-gray-500">
                    <FileText className="w-12 h-12 mx-auto mb-3" />
                    <h3 className="text-base font-medium mb-2">No IPO Generated</h3>
                    <p className="text-sm">Upload a DRHP PDF and generate IPO notes to view them here</p>
                  </div>
                </div>
              ) : isGeneratingNotes || isGeneratingPdf ? ( // Add isGeneratingPdf to loading state
                <div className="h-full flex items-center justify-center">
                  <div className="text-center">
                    <div className="relative mb-6">
                      <div className="w-16 h-16 border-4 border-[#FFB703]/20 rounded-full animate-spin border-t-[#FFB703] mx-auto"></div>
                      <FileText className="w-6 h-6 absolute top-1/2 left-1/2 transform -translate-x-1/2 -translate-y-1/2 text-[#FFB703]" />
                    </div>
                    <h3 className="text-lg font-semibold mb-2 text-[#023047]">
                      {isGeneratingPdf ? "Generating PDF Report..." : "Generating IPO Notes..."}
                    </h3>
                    <p className="text-gray-600 text-sm mb-2">Please have patience, the IPO Note is being processed</p>
                    <p className="text-xs text-gray-500">This may take a few minutes to complete</p>
                  </div>
                </div>
              ) : (
                <div className="prose prose-sm max-w-none h-full">
                  <div className="bg-white p-4 rounded-lg border depth-content h-full">
                    {generatedPdfBlobUrl ? (
                      <iframe
                        src={generatedPdfBlobUrl}
                        className="w-full h-full border-0 rounded-lg"
                        title="Generated IPO Notes PDF"
                      />
                    ) : (
                      <div className="flex items-center justify-center p-8 min-h-[600px]">
                        <div className="text-center text-gray-500">
                          <Eye className="w-12 h-12 mx-auto mb-3" />
                          <h3 className="text-lg font-medium mb-2">PDF Report Preview</h3>
                          <p className="text-sm">Your generated PDF report will appear here</p>
                        </div>
                      </div>
                    )}
                  </div>
                </div>
              )}
            </div>
          </Card>
        </div>
      </div>

      {/* Dialogs */}
      <Dialog open={showGenerateConfirm} onOpenChange={setShowGenerateConfirm}>
        <DialogContent className="depth-dialog max-h-[95vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>Generate IPO Notes</DialogTitle>
          </DialogHeader>
          <p>Do you want to continue with generating IPO notes for this DRHP document?</p>
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowGenerateConfirm(false)} className="depth-button">
              Cancel
            </Button>
            <Button
              onClick={confirmGenerate}
              className="bg-[#FFB703] hover:bg-[#FB8500] text-white depth-button glow-orange"
            >
              Continue
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={showRemoveConfirm} onOpenChange={setShowRemoveConfirm}>
        <DialogContent className="depth-dialog max-h-[95vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>Remove PDF</DialogTitle>
          </DialogHeader>
          <p>Are you sure you want to remove the uploaded PDF? This will also clear any generated IPO notes.</p>
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowRemoveConfirm(false)} className="depth-button">
              Cancel
            </Button>
            <Button variant="destructive" onClick={confirmRemove} className="depth-button">
              Remove
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={!!showWarning} onOpenChange={() => setShowWarning("")}>
        <DialogContent className="depth-dialog max-h-[95vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle className="flex items-center space-x-2">
              <AlertCircle className="w-5 h-5 text-amber-500" />
              <span>Warning</span>
            </DialogTitle>
          </DialogHeader>
          <p>{showWarning}</p>
          <DialogFooter>
            <Button onClick={() => setShowWarning("")} className="depth-button">
              OK
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
      {/* Company Detail Modal */}
      <Dialog open={showCompanyDetail} onOpenChange={setShowCompanyDetail}>
        <DialogContent className="max-w-6xl max-h-[90vh] depth-dialog flex flex-col">
          <DialogHeader className="border-b pb-4">
            <div className="flex items-center justify-between">
              <div>
                <DialogTitle className="text-xl font-bold">{selectedCompanyDetail?.name}</DialogTitle>
                <div className="flex items-center space-x-4 mt-2 text-sm text-gray-600">
                  <span>UIN: {selectedCompanyDetail?.uin}</span>
                  <span>Uploaded: {selectedCompanyDetail?.uploadDate}</span>
                  <Badge
                    variant="outline"
                    className={`text-xs ${
                      selectedCompanyDetail?.status === "completed"
                        ? "bg-green-50 text-green-700 border-green-200"
                        : "bg-blue-50 text-blue-700 border-blue-200"
                    }`}
                  >
                    {selectedCompanyDetail?.status.toUpperCase()}
                  </Badge>
                </div>
              </div>
              <div className="flex items-center space-x-2">
                <Button
                  onClick={handleRegenerateReport}
                  disabled={isLoadingCompanyReport}
                  size="sm"
                  className="bg-gradient-to-r from-[#219EBC] to-[#023047] hover:from-[#023047] hover:to-[#219EBC] text-white depth-button"
                >
                  {isLoadingCompanyReport ? (
                    <Loader2 className="w-3 h-3 mr-1 animate-spin" />
                  ) : (
                    <Play className="w-3 h-3 mr-1" />
                  )}
                  Re-generate Report
                </Button>
                <Button onClick={handleDeleteCompany} variant="destructive" size="sm" className="depth-button">
                  <Trash2 className="w-3 h-3 mr-1" />
                  Delete Company
                </Button>
              </div>
            </div>
          </DialogHeader>

          <div className="flex-1 overflow-auto mt-4">
            {isLoadingCompanyReport ? (
              <div className="h-full flex items-center justify-center">
                <div className="text-center">
                  <Loader2 className="w-10 h-10 mx-auto mb-3 animate-spin text-[#219EBC]" />
                  <h3 className="text-base font-medium mb-2">Loading Report...</h3>
                  <p className="text-gray-500 text-sm">Fetching data from database</p>
                </div>
              </div>
            ) : companyReportPdfBlobUrl ? ( // Check for PDF URL
              <div className="prose prose-sm max-w-none h-full">
                <div className="bg-white p-6 rounded-lg border depth-content h-full">
                  <iframe
                    src={companyReportPdfBlobUrl}
                    className="w-full h-full border-0 rounded-lg"
                    title="Company Report PDF"
                  />
                </div>
              </div>
            ) : (
              <div className="h-full flex items-center justify-center">
                <div className="text-center text-gray-500">
                  <FileText className="w-12 h-12 mx-auto mb-3" />
                  <h3 className="text-base font-medium mb-2">No Report Available</h3>
                  <p className="text-sm">This company doesn't have a generated report yet</p>
                </div>
              </div>
            )}
          </div>
        </DialogContent>
      </Dialog>
    </div>
  )
}
