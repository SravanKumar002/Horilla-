$(document).ready(function () {
  // const customColors = [
  //   "#5F489D",
  //   "#E49394",
  //   "#AF9962",
  //   "rgb(75, 192, 192)",
  //   "rgb(153, 102, 255)",
  //   "rgb(255, 159, 64)",
  // ];
  const customColors = ["#8C52FF"];

  function employeeChart(dataSet, labels) {
    const data = {
      labels: labels,
      datasets: dataSet,
    };
    // Create chart using the Chart.js library
    // console.log(data.datasets)
    window["myChart"] = {};
    if (document.getElementById("totalEmployees")) {
      const ctx = document.getElementById("totalEmployees").getContext("2d");
      data.datasets[0].backgroundColor = customColors;
      employeeChart = new Chart(ctx, {
        type: "doughnut",
        data: data,
        options: {
          responsive: true,
          maintainAspectRatio: false,
          onClick: (e, activeEls) => {
            let datasetIndex = activeEls[0].datasetIndex;
            let dataIndex = activeEls[0].index;
            let datasetLabel = e.chart.data.datasets[datasetIndex].label;
            let value = e.chart.data.datasets[datasetIndex].data[dataIndex];
            let label = e.chart.data.labels[dataIndex];
            var active = "False";
            if (label.toLowerCase() == "active") {
              active = "True";
            }
            localStorage.removeItem("savedFilters");
            window.location.href =
              "/employee/employee-view?is_active=" + active;
          },
        },
        plugins: [
          {
            afterRender: (chart) => emptyChart(chart),
          },
        ],
      });
    }
  }

  const customColors1 = ["#8c52ff", "#bea1f7", "#5e17eb"];

  function genderChart(dataSet, labels) {
    const data = {
      labels: labels,
      datasets: dataSet,
    };
    // Create chart using the Chart.js library

    // console.log(data.datasets)
    window["genderChart"] = {};
    if (document.getElementById("genderChart")) {
      const ctx = document.getElementById("genderChart").getContext("2d");
      //   applyCustomColors(dataSet);
      data.datasets[0].backgroundColor = customColors1;
      genderChart = new Chart(ctx, {
        type: "doughnut",
        data: data,
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: {
            legend: {
              position: "bottom",
              labels: {
              usePointStyle: true,
              pointStyle: "circle",
              },
             },
            
          },
          onClick: (e, activeEls) => {
            let datasetIndex = activeEls[0].datasetIndex;
            let dataIndex = activeEls[0].index;
            let datasetLabel = e.chart.data.datasets[datasetIndex].label;
            let value = e.chart.data.datasets[datasetIndex].data[dataIndex];
            let label = e.chart.data.labels[dataIndex];
            localStorage.removeItem("savedFilters");
            window.location.href =
              "/employee/employee-view?gender=" + label.toLowerCase();
          },
        },
        plugins: [
          {
            afterRender: (chart) => emptyChart(chart),
          },
        ],
      });
    }
  }

  //   function genderChart(dataSet, labels) {
  //   const data = {
  //     labels: labels,
  //     datasets: dataSet,
  //   };

  //   window["genderChart"] = {};

  //   if (document.getElementById("genderChart")) {
  //     const ctx = document.getElementById("genderChart").getContext("2d");

  //     data.datasets[0].backgroundColor = customColors1;

  //     genderChart = new Chart(ctx, {
  //       type: "doughnut",
  //       data: data,
  //       options: {
  //         responsive: true,
  //         maintainAspectRatio: false,
  //         plugins: {
  //           legend: {
  //             display: true,
  //             position: "bottom", // 👈 Niche aa jayega
  //             labels: {
  //               usePointStyle: true,
  //               pointStyle: "rect",
  //               boxWidth: 20,     // 👈 equal width box
  //                boxHeight: 12,    // 👈 perfect height
  //               padding: 12,
  //             },
  //           },
  //         },
  //         onClick: (e, activeEls) => {
  //           let datasetIndex = activeEls[0].datasetIndex;
  //           let dataIndex = activeEls[0].index;
  //           let label = e.chart.data.labels[dataIndex];
  //           localStorage.removeItem("savedFilters");
  //           window.location.href =
  //             "/employee/employee-view?gender=" + label.toLowerCase();
  //         },
  //       },
  //       plugins: [
  //         {
  //           afterRender: (chart) => emptyChart(chart),
  //         },
  //       ],
  //     });
  //   }
  // }

  function departmentChart(dataSet, labels) {
    const data = {
        labels: labels,
        datasets: dataSet,
    };

    window["departmentChart"] = {};
    if (document.getElementById("departmentChart")) {
        const ctx = document.getElementById("departmentChart").getContext("2d");

        // Custom styling logic
        if (data.datasets.length > 0) {
            data.datasets[0].backgroundColor = customColors;
        }

        data.datasets.forEach((ds) => {
            ds.borderRadius = {
                topLeft: 8,
                topRight: 8,
                bottomLeft: 0,
                bottomRight: 0,
            };
            ds.borderSkipped = "bottom";
        });

        departmentChart = new Chart(ctx, {
            type: "bar",
            data: data,
            options: {
                responsive: true,
                maintainAspectRatio: false,
                scales: {
                    x: {
                        stacked: true,
                        // X-axis par sirf labels hote hain (IT, HR), precision yahan kaam nahi karega
                    },
                    y: {
                        beginAtZero: true,
                        stacked: true,
                        ticks: {
                            // --- FIX: YAHAN CHANGES KIYE HAIN ---
                            stepSize: 1,       // Force 1, 2, 3 instead of 0.1, 0.2
                            precision: 0,      // No decimals allowed
                            callback: function (value) {
                                if (value % 1 === 0) {
                                    return value; // Sirf whole numbers dikhao
                                }
                            }
                        },
                    },
                },
                plugins: {
                    legend: {
                        display: false,
                    },
                },
                onClick: (e, activeEls) => {
                    // Safety check: click bar par hua hai ya nahi
                    if (activeEls.length > 0) {
                        let dataIndex = activeEls[0].index;
                        let label = e.chart.data.labels[dataIndex];
                        
                        localStorage.removeItem("savedFilters");
                        window.location.href = "/employee/employee-view?department=" + encodeURIComponent(label);
                    }
                },
            },
            plugins: [
                {
                    afterRender: (chart) => emptyChart(chart),
                },
            ],
        });
    }
}

  $.ajax({
    url: "/employee/dashboard-employee",
    type: "GET",
    success: function (response) {
      // Code to handle the response
      dataSet = response.dataSet;
      labels = response.labels;
      // console.log("/employee/dashboard-employee dataSet:-",dataSet);
      // console.log("/employee/dashboard-employee labels:-",labels);
      employeeChart(dataSet, labels);
    },
  });

  $.ajax({
    url: "/employee/dashboard-employee-gender",
    type: "GET",
    success: function (response) {
      // Code to handle the response
      dataSet = response.dataSet;
      labels = response.labels;
      genderChart(dataSet, labels);
    },
  });

  $.ajax({
    url: "/employee/dashboard-employee-department",
    type: "GET",
    success: function (response) {
      // Code to handle the response
      dataSet = response.dataSet;
      labels = response.labels;
      departmentChart(dataSet, labels);
    },
    error: function (error) {
      console.log(error);
    },
  });

  $(".oh-card-dashboard__title").click(function (e) {
    var chartType = myChart.config.type;
    if (chartType === "line") {
      chartType = "bar";
    } else if (chartType === "bar") {
      chartType = "doughnut";
    } else if (chartType === "doughnut") {
      chartType = "pie";
    } else if (chartType === "pie") {
      chartType = "line";
    }
    myChart.config.type = chartType;
    myChart.update();
  });
});
